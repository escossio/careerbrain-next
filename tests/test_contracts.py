import copy
import json
import socket
import unittest

from jsonschema import Draft202012Validator

from tools.contracts import (
    ContractError, Producer, ROOT, SCHEMAS, digest, eligible, ingestion,
    instant, may_save_profile, public_https, replay_decision, strict_load,
    validate, validate_evidence, validate_page,
)


def example(name):
    return json.loads((ROOT / "contracts/examples" / f"{name}.json").read_text())


def context(value):
    vacancy = value["records"][0]["vacancy"]
    event = vacancy["event"]
    proof = event["provenance"]
    trusted = {**proof, "producer_id": "producer-test", "source_id": vacancy["source_id"],
               "source_event_id": event["source_event_id"], "published_at": event["published_at"]}
    return Producer("producer-test", frozenset({vacancy["source_id"]}),
                    {proof["evidence_id"]: trusted}, frozenset({vacancy["access"]["value"]}))


class SchemaTests(unittest.TestCase):
    def test_all_schemas_valid_and_examples_covered(self):
        for name, schema in SCHEMAS.items():
            with self.subTest(schema=name):
                Draft202012Validator.check_schema(schema)
                if name != "common":
                    validate(name, example(name))

    def test_unknown_fields_rejected_in_every_envelope(self):
        for name in SCHEMAS:
            if name == "common":
                continue
            with self.subTest(schema=name):
                value = example(name)
                value["unexpected_field"] = "not-permitted"
                with self.assertRaises(ContractError):
                    validate(name, value)

    def test_required_fields_rejected(self):
        for name, schema in SCHEMAS.items():
            if name == "common":
                continue
            for field in schema["required"]:
                with self.subTest(schema=name, missing=field):
                    value = example(name)
                    del value[field]
                    with self.assertRaises(ContractError):
                        validate(name, value)

    def test_unknown_schema_version_rejected(self):
        value = example("ingestion-batch")
        value["schema_version"] = "careerbrain.ingestion.v2"
        with self.assertRaises(ContractError):
            validate("ingestion-batch", value)

    def test_blank_title_and_insufficient_description(self):
        for field, bad in [("title", "   "), ("description", "short")]:
            with self.subTest(field=field):
                value = example("ingestion-batch")
                value["records"][0]["vacancy"][field] = bad
                with self.assertRaises(ContractError):
                    validate("ingestion-batch", value)

    def test_json_duplicate_keys_nan_wrong_utf8_depth_and_limit(self):
        for raw in [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'\xff',
                    b'[]', b'{"a":'+b'['*40+b'0'+b']'*40+b'}', b' '*1_048_577]:
            with self.subTest(case=len(raw)):
                with self.assertRaises(ContractError):
                    strict_load(raw)

    def test_payload_without_contact_is_rejected(self):
        value = example("ingestion-batch")
        del value["records"][0]["vacancy"]["access"]
        with self.assertRaises(ContractError):
            validate("ingestion-batch", value)

    def test_no_tenant_or_producer_override_in_ingestion(self):
        for field in ["tenant_id", "producer_id"]:
            value = example("ingestion-batch")
            value[field] = "someone-else"
            with self.assertRaises(ContractError):
                validate("ingestion-batch", value)

    def test_batch_item_limit(self):
        value = example("ingestion-batch")
        value["records"] *= 101
        with self.assertRaises(ContractError):
            validate("ingestion-batch", value)

    def test_private_queue_cannot_contain_raw_resume(self):
        for field in ["resume_text", "file_bytes", "prompt", "access_token"]:
            value = example("resume-job")
            value[field] = "synthetic-content"
            with self.assertRaises(ContractError):
                validate("resume-job", value)

    def test_upload_size_type_and_identity_override(self):
        for field, bad in [("content_length", 5_242_881), ("content_type", "text/html"),
                           ("tenant_id", "other-user")]:
            value = example("resume-upload")
            value[field] = bad
            with self.assertRaises(ContractError):
                validate("resume-upload", value)

    def test_profile_v2_represents_uncertainty_without_a_fictitious_attribute(self):
        uncertain = example("private-profile-v2")
        validate("private-profile-v2", uncertain)
        for status, attributes in [("READY", []), ("UNCERTAIN", [example("private-profile")["attributes"][0]])]:
            with self.subTest(status=status), self.assertRaises(ContractError):
                value = copy.deepcopy(uncertain)
                value["status"], value["attributes"] = status, attributes
                validate("private-profile-v2", value)
        legacy = example("private-profile")
        legacy["status"], legacy["attributes"] = "UNCERTAIN", []
        with self.assertRaises(ContractError):
            validate("private-profile", legacy)

    def test_match_can_express_absent_evidence_without_a_fictitious_score(self):
        value = example("match")
        value["affinity"] = value["confidence"] = None
        value["reasons"] = ["REQUIREMENT_UNKNOWN"]
        validate("match", value)


class TimeTests(unittest.TestCase):
    def test_before_equal_after_and_utc_equivalence(self):
        account = "2026-10-21T12:00:00Z"
        for publication, expected in [
            ("2026-10-21T11:59:59.999999Z", False), (account, True),
            ("2026-10-21T12:00:00.000001Z", True), ("2026-10-21T09:00:00-03:00", True),
        ]:
            with self.subTest(publication=publication):
                self.assertEqual(eligible(publication, account), expected)
        self.assertFalse(eligible(account, account, active=False))

    def test_ambiguous_invalid_dates_rejected(self):
        for value in ["2026-10-21", "2026-10-21T12:00:00", "2026-02-30T12:00:00Z",
                      "2026-10-21T12:00:60Z", "2026-10-21T12:00:00+15:00",
                      "2026-10-21T12:00:00.1234567Z"]:
            with self.subTest(value=value):
                with self.assertRaises(ContractError):
                    instant(value)

    def test_import_profile_and_score_cannot_reset_cutoff(self):
        identity = example("identity")
        original = identity["account_created_at"]
        for _ in range(3):
            self.assertFalse(eligible("2026-10-20T23:00:00Z", original))
        self.assertNotIn("account_created_at", SCHEMAS["resume-upload"]["properties"])


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.value = example("ingestion-batch")
        self.producer = context(self.value)

    def check(self, value=None, producer=None, known=None):
        return ingestion(json.dumps(value or self.value).encode(), key="batch-synthetic-1",
                         now="2026-10-21T14:00:00Z", producer=producer or self.producer,
                         known_events=known)

    def test_authorized_original(self):
        self.assertEqual(self.check(), self.value)

    def test_unknown_producer_source_or_evidence_rejected(self):
        for change in ["producer", "source", "evidence", "authorization", "digest"]:
            value = copy.deepcopy(self.value)
            vacancy = value["records"][0]["vacancy"]
            proof = vacancy["event"]["provenance"]
            producer = self.producer
            if change == "producer":
                producer = Producer("different", producer.sources, producer.evidence,
                                    producer.official_contacts)
            elif change == "source":
                vacancy["source_id"] = "unapproved"
            else:
                field = {"evidence": "evidence_id", "authorization": "authorization_id",
                         "digest": "evidence_sha256"}[change]
                proof[field] = "b"*64 if change == "digest" else "unapproved"
            with self.subTest(change=change), self.assertRaises(ContractError):
                self.check(value, producer)

    def test_future_ambiguous_mismatched_publication(self):
        for date in ["2026-10-22T12:00:00Z", "2026-10-21", "2026-10-21T11:00:00Z"]:
            value = copy.deepcopy(self.value)
            value["records"][0]["vacancy"]["event"]["published_at"] = date
            with self.subTest(date=date), self.assertRaises(ContractError):
                self.check(value)

    def test_future_observation(self):
        value = copy.deepcopy(self.value)
        value["records"][0]["vacancy"]["event"]["provenance"]["observed_at"] = "2026-10-22T12:00:00Z"
        with self.assertRaises(ContractError):
            self.check(value)

    def test_contact_syntax_and_authority_are_separate(self):
        value = copy.deepcopy(self.value)
        value["records"][0]["vacancy"]["access"] = {"kind": "https", "value": "https://example.org/unapproved"}
        with self.assertRaises(ContractError) as raised:
            self.check(value)
        self.assertEqual(raised.exception.code, "INVALID_CONTACT")

    def test_republication_requires_previous_proof_and_later_instant(self):
        value = copy.deepcopy(self.value)
        event = value["records"][0]["vacancy"]["event"]
        event["kind"] = "republication"
        with self.assertRaises(ContractError):
            self.check(value)
        event["previous_source_event_id"] = "publication-old"
        with self.assertRaises(ContractError):
            self.check(value)
        old = {"source_vacancy_id": "maintenance-1", "published_at": "2026-10-20T12:00:00Z",
               "evidence_id": "evidence-old", "content_digest": "old"}
        known = {("synthetic-source", "publication-old"): old}
        self.check(value, known=known)
        old["published_at"] = event["published_at"]
        with self.assertRaises(ContractError):
            self.check(value, known=known)

    def test_duplicate_event_equal_content_and_conflicting_content(self):
        vacancy = self.value["records"][0]["vacancy"]
        known = {("synthetic-source", "publication-new"): {"content_digest": digest(vacancy)}}
        self.check(known=known)
        value = copy.deepcopy(self.value)
        value["records"][0]["vacancy"]["title"] = "Cosmetic edit"
        with self.assertRaises(ContractError):
            self.check(value, known=known)

    def test_bad_item_prevents_whole_batch_acceptance(self):
        value = copy.deepcopy(self.value)
        bad = copy.deepcopy(value["records"][0])
        bad["vacancy"]["event"]["published_at"] = "ambiguous"
        value["records"].append(bad)
        with self.assertRaises(ContractError):
            self.check(value)
        # Only a validation oracle: database atomicity must be tested in pass 04.

    def test_conflicting_same_event_inside_batch(self):
        value = copy.deepcopy(self.value)
        changed = copy.deepcopy(value["records"][0])
        changed["vacancy"]["title"] = "Different title"
        value["records"].append(changed)
        with self.assertRaises(ContractError):
            self.check(value)

    def test_key_must_match_batch(self):
        with self.assertRaises(ContractError):
            ingestion(json.dumps(self.value).encode(), key="different", now="2026-10-21T14:00:00Z",
                      producer=self.producer)

    def test_correction_cannot_change_publication_instant(self):
        value = copy.deepcopy(self.value)
        value["records"] = [{"operation": "correct", "source_id": "synthetic-source",
                              "source_vacancy_id": "maintenance-1", "source_event_id": "publication-new",
                              "source_revision": "revision-2", "provenance": value["records"][0]["vacancy"]["event"]["provenance"],
                              "correction": {"published_at": "2026-10-21T13:30:00Z"}}]
        with self.assertRaises(ContractError):
            self.check(value)
        value["records"][0]["correction"] = {"title": "Corrected title"}
        known = {("synthetic-source", "publication-new"): {"source_vacancy_id": "maintenance-1"}}
        self.check(value, known=known)


class ProtocolTests(unittest.TestCase):
    def test_canonical_digest_key_order_and_array_order(self):
        self.assertEqual(digest({"b": "á", "a": 1}), digest({"a": 1, "b": "á"}))
        self.assertNotEqual(digest({"items": [1, 2]}), digest({"items": [2, 1]}))

    def test_idempotency_conflict_and_in_progress(self):
        self.assertEqual(replay_decision(None, "a"), "NEW")
        self.assertEqual(replay_decision("a", "a"), "REPLAY")
        for candidate, committed, code in [("b", True, "IDEMPOTENCY_CONFLICT"),
                                            ("a", False, "BATCH_IN_PROGRESS")]:
            with self.assertRaises(ContractError) as raised:
                replay_decision("a", candidate, committed)
            self.assertEqual(raised.exception.code, code)

    def test_urls_reject_private_credentials_and_non_https(self):
        for url in ["http://example.org/job", "https://127.0.0.1/job", "https://10.0.0.1/",
                    "https://[::1]/", "https://localhost/", "https://service.internal/",
                    "https://" + "user:pass" + "@example.org/", "https://example.org/?token=not-a-token",
                    "file:///etc/passwd", "https://2130706433/", "https://example.org/#fragment"]:
            with self.subTest(url=url):
                self.assertFalse(public_https(url))
        self.assertTrue(public_https("https://example.org/jobs/1"))

    def test_semantic_output_requires_exact_evidence(self):
        profile = example("private-profile")
        source = (ROOT / "tests/synthetic-source.txt").read_text().strip()
        validate_evidence(source, profile, schema="private-profile")
        for bad in ["missing", "invented", "offset"]:
            value = copy.deepcopy(profile)
            if bad == "missing":
                value["attributes"][0]["evidence"] = []
            elif bad == "invented":
                value["attributes"][0]["evidence"][0]["quote"] = "invented qualification"
            else:
                value["attributes"][0]["evidence"][0]["start"] = 1000
            with self.subTest(case=bad), self.assertRaises(ContractError):
                validate_evidence(source, value, schema="private-profile")

    def test_explicit_global_semantics_have_source_evidence(self):
        source = example("ingestion-batch")["records"][0]["vacancy"]["description"]
        validate_evidence(source, example("vacancy-semantics"), schema="vacancy-semantics")

    def test_stale_generation_deletion_epoch_and_inactive_account(self):
        good = dict(account_state="ACTIVE", current_generation=2, job_generation=2,
                    current_epoch=0, job_epoch=0)
        self.assertTrue(may_save_profile(**good))
        for field, bad in [("job_generation", 1), ("job_epoch", 1), ("account_state", "DELETING")]:
            self.assertFalse(may_save_profile(**{**good, field: bad}))

    def test_page_sequence_order_watermark_duplicates_and_cursor(self):
        page = example("sync-page")
        validate_page(page, after=6)
        for bad in ["duplicate", "watermark", "after", "cursor"]:
            value = copy.deepcopy(page)
            after = 6
            if bad == "duplicate":
                value["items"] *= 2
            elif bad == "watermark":
                value["snapshot_high_watermark"] = 6
            elif bad == "after":
                after = 7
            else:
                value["next_cursor"] = None
            with self.subTest(case=bad), self.assertRaises(ContractError):
                validate_page(value, after=after)

    def test_late_classification_uses_new_availability_sequence(self):
        page = example("sync-page")
        # Earlier publication can finish after a previous sync; availability sequence wins.
        page["items"][0]["sequence"] = 8
        page["snapshot_high_watermark"] = 8
        page["items"][0]["available_at"] = "2026-10-21T14:00:00Z"
        validate_page(page, after=7)

    def test_tts_rejects_raw_text_profile_or_user_fields(self):
        for field in ["text", "profile", "tenant_id", "resume"]:
            value = example("tts-request")
            value[field] = "synthetic"
            with self.assertRaises(ContractError):
                validate("tts-request", value)

    def test_account_identifier_not_accepted_in_application_command(self):
        value = example("application-command")
        value["tenant_id"] = "other-tenant"
        with self.assertRaises(ContractError):
            validate("application-command", value)

    def test_network_is_denied(self):
        with self.assertRaisesRegex(RuntimeError, "OFFLINE_IO_BLOCKED"):
            socket.socket()


if __name__ == "__main__":
    unittest.main()

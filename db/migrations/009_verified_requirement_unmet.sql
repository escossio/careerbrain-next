-- Pass 07 extension: V1/V2 attributes never prove a negative.  Only the
-- versioned pair retained below may hide a recommendation as REQUIREMENT_UNMET.
ALTER TABLE private.profiles
  ADD COLUMN contract_version text NOT NULL DEFAULT 'careerbrain.profile.v2'
    CHECK(contract_version IN ('careerbrain.profile.v2','careerbrain.profile.v3')),
  ADD COLUMN source_version text,
  ADD COLUMN negative_attestations jsonb NOT NULL DEFAULT '[]'::jsonb
    CHECK(jsonb_typeof(negative_attestations)='array');

ALTER TABLE private.recommendations
  ADD COLUMN requirement_proofs jsonb NOT NULL DEFAULT '[]'::jsonb
    CHECK(jsonb_typeof(requirement_proofs)='array');

CREATE OR REPLACE VIEW private.current_recommendations WITH (security_invoker=true) AS
  SELECT r.recommendation_id,r.tenant_id,r.event_id,r.profile_version,r.policy_version,
    r.affinity,r.confidence,r.reasons,r.classification_cache_id,r.requirement_proofs
  FROM private.recommendations r
  JOIN private.profiles p ON p.tenant_id=r.tenant_id
  JOIN private.match_requests q ON q.tenant_id=r.tenant_id AND q.event_id=r.event_id
    AND q.profile_version=r.profile_version AND q.classification_cache_id=r.classification_cache_id
    AND q.policy_version=r.policy_version
  JOIN catalog.current_classifications c ON c.event_id=r.event_id AND c.cache_id=r.classification_cache_id
  JOIN ops.matching_policy policy ON policy.singleton AND policy.policy_version=r.policy_version
  WHERE p.profile_version=r.profile_version AND private.event_eligible(r.tenant_id,r.event_id)
    AND NOT ('REQUIREMENT_UNMET'=ANY(r.reasons));

CREATE FUNCTION private.complete_match_job(job uuid,owner uuid,fence bigint,result_affinity numeric,
  result_confidence numeric,result_reasons text[],result_requirement_proofs jsonb) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE result text;
BEGIN
  IF session_user<>'cb_private_worker' THEN RAISE EXCEPTION 'worker denied' USING ERRCODE='42501'; END IF;
  IF jsonb_typeof(result_requirement_proofs)<>'array' THEN
    RAISE EXCEPTION 'invalid match proof' USING ERRCODE='22023';
  END IF;
  IF result_reasons @> ARRAY['REQUIREMENT_UNMET']::text[] THEN
    IF result_reasons<>ARRAY['REQUIREMENT_UNMET']::text[] OR result_affinity IS NOT NULL
       OR result_confidence IS NOT NULL OR jsonb_array_length(result_requirement_proofs) NOT BETWEEN 1 AND 20 THEN
      RAISE EXCEPTION 'invalid unmet result' USING ERRCODE='22023';
    END IF;
    -- The established function performs all lease, fencing and freshness checks.
    result:=private.complete_match_job(job,owner,fence,NULL,NULL,ARRAY['REQUIREMENT_UNKNOWN']::text[]);
    IF result='READY' THEN
      UPDATE private.recommendations r SET reasons=ARRAY['REQUIREMENT_UNMET']::text[],
        requirement_proofs=result_requirement_proofs
      FROM private.match_requests request
      WHERE request.job_id=job AND r.tenant_id=request.tenant_id AND r.event_id=request.event_id;
    END IF;
    RETURN result;
  END IF;
  IF jsonb_array_length(result_requirement_proofs)<>0 THEN
    RAISE EXCEPTION 'unexpected match proof' USING ERRCODE='22023';
  END IF;
  RETURN private.complete_match_job(job,owner,fence,result_affinity,result_confidence,result_reasons);
END $$;

-- Grant only schema lookup needed for the already-scoped classification view.
GRANT USAGE ON SCHEMA catalog TO cb_private_worker;

GRANT EXECUTE ON FUNCTION private.complete_match_job(uuid,uuid,bigint,numeric,numeric,text[],jsonb)
  TO cb_private_worker;

-- Session state is owned by cb_owner; runtime roles get functions, never table access.
CREATE SCHEMA auth;
REVOKE ALL ON SCHEMA auth FROM PUBLIC;

CREATE TABLE auth.challenges (
  id uuid PRIMARY KEY,
  nonce_digest text NOT NULL CHECK (nonce_digest ~ '^[a-f0-9]{64}$'),
  created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
  expires_at timestamptz NOT NULL DEFAULT transaction_timestamp() + interval '5 minutes',
  consumed_at timestamptz,
  CHECK (expires_at <= created_at + interval '5 minutes')
);
CREATE TABLE auth.sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id uuid NOT NULL REFERENCES identity.accounts ON DELETE CASCADE,
  access_digest text NOT NULL UNIQUE CHECK (access_digest ~ '^[a-f0-9]{64}$'),
  refresh_digest text NOT NULL UNIQUE CHECK (refresh_digest ~ '^[a-f0-9]{64}$'),
  created_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
  absolute_expires_at timestamptz NOT NULL DEFAULT transaction_timestamp() + interval '30 days',
  last_used_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
  access_expires_at timestamptz NOT NULL DEFAULT transaction_timestamp() + interval '15 minutes',
  revoked_at timestamptz,
  CHECK (absolute_expires_at <= created_at + interval '30 days'),
  CHECK (access_expires_at <= last_used_at + interval '15 minutes')
);
CREATE TABLE auth.used_refresh (
  digest text PRIMARY KEY CHECK (digest ~ '^[a-f0-9]{64}$'),
  session_id uuid NOT NULL REFERENCES auth.sessions ON DELETE CASCADE,
  consumed_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);
CREATE INDEX auth_sessions_account ON auth.sessions(account_id);

ALTER TABLE auth.challenges ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth.challenges FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_internal ON auth.challenges TO cb_owner USING(true) WITH CHECK(true);
ALTER TABLE auth.sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth.sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_internal ON auth.sessions TO cb_owner USING(true) WITH CHECK(true);
ALTER TABLE auth.used_refresh ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth.used_refresh FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_internal ON auth.used_refresh TO cb_owner USING(true) WITH CHECK(true);

CREATE FUNCTION auth.issue_challenge(challenge uuid, digest text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  INSERT INTO auth.challenges(id,nonce_digest) VALUES(challenge,digest);
END $$;

CREATE FUNCTION auth.consume_challenge(challenge uuid, digest text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  UPDATE auth.challenges SET consumed_at=transaction_timestamp()
  WHERE id=challenge AND nonce_digest=digest AND consumed_at IS NULL
    AND expires_at>transaction_timestamp();
  RETURN FOUND;
END $$;

CREATE FUNCTION auth.issue_session(account uuid, access_hash text, refresh_hash text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  PERFORM 1 FROM identity.accounts a WHERE a.id=account AND a.state='ACTIVE' FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'account unavailable' USING ERRCODE='42501'; END IF;
  INSERT INTO auth.sessions(account_id,access_digest,refresh_digest)
    VALUES(account,access_hash,refresh_hash);
END $$;

CREATE FUNCTION auth.rotate_session(old_hash text, access_hash text, refresh_hash text)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE current_session auth.sessions%ROWTYPE; replayed uuid;
BEGIN
  SELECT * INTO current_session FROM auth.sessions WHERE refresh_digest=old_hash FOR UPDATE;
  IF NOT FOUND THEN
    SELECT session_id INTO replayed FROM auth.used_refresh WHERE digest=old_hash;
    IF replayed IS NOT NULL THEN
      UPDATE auth.sessions SET revoked_at=transaction_timestamp()
        WHERE id=replayed AND revoked_at IS NULL;
      RETURN 'REPLAY';
    END IF;
    RETURN 'DENIED';
  END IF;
  IF current_session.revoked_at IS NOT NULL
     OR current_session.absolute_expires_at<=transaction_timestamp()
     OR current_session.last_used_at+interval '7 days'<=transaction_timestamp()
     OR NOT EXISTS (SELECT FROM identity.accounts a
                    WHERE a.id=current_session.account_id AND a.state='ACTIVE') THEN
    RETURN 'DENIED';
  END IF;
  INSERT INTO auth.used_refresh(digest,session_id) VALUES(old_hash,current_session.id);
  UPDATE auth.sessions SET access_digest=access_hash, refresh_digest=refresh_hash,
    last_used_at=transaction_timestamp(), access_expires_at=transaction_timestamp()+interval '15 minutes'
    WHERE id=current_session.id;
  RETURN 'OK';
END $$;

CREATE FUNCTION auth.resolve_access(access_hash text)
RETURNS TABLE(user_id uuid,tenant_id uuid,issuer text,subject text,
              account_created_at timestamptz,state text,profile_status text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
  SELECT a.id,t.id,e.issuer,e.subject,a.account_created_at,a.state,
    CASE WHEN p.tenant_id IS NULL THEN 'MISSING' ELSE 'READY' END
  FROM auth.sessions s JOIN identity.accounts a ON a.id=s.account_id
  JOIN private.tenants t ON t.account_id=a.id
  JOIN identity.external_identities e ON e.account_id=a.id
  LEFT JOIN private.profiles p ON p.tenant_id=t.id
  WHERE s.access_digest=access_hash AND s.revoked_at IS NULL AND a.state='ACTIVE'
    AND s.access_expires_at>transaction_timestamp()
    AND s.absolute_expires_at>transaction_timestamp()
    AND s.last_used_at+interval '7 days'>transaction_timestamp()
  LIMIT 1
$$;

CREATE FUNCTION auth.revoke_access(access_hash text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  UPDATE auth.sessions SET revoked_at=transaction_timestamp()
  WHERE access_digest=access_hash AND revoked_at IS NULL
    AND access_expires_at>transaction_timestamp()
    AND absolute_expires_at>transaction_timestamp();
  RETURN FOUND;
END $$;

CREATE FUNCTION auth.revoke_on_deletion() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
  IF NEW.state='DELETING' AND OLD.state='ACTIVE' THEN
    UPDATE auth.sessions SET revoked_at=transaction_timestamp()
      WHERE account_id=NEW.id AND revoked_at IS NULL;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER revoke_on_deletion AFTER UPDATE OF state ON identity.accounts
FOR EACH ROW EXECUTE FUNCTION auth.revoke_on_deletion();

GRANT USAGE ON SCHEMA auth TO cb_auth,cb_api;
REVOKE ALL ON ALL TABLES IN SCHEMA auth FROM PUBLIC,cb_auth,cb_api;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA auth FROM PUBLIC;
GRANT EXECUTE ON FUNCTION auth.issue_challenge(uuid,text),auth.consume_challenge(uuid,text),
  auth.issue_session(uuid,text,text),auth.rotate_session(text,text,text) TO cb_auth;
GRANT EXECUTE ON FUNCTION auth.resolve_access(text),auth.revoke_access(text) TO cb_api;

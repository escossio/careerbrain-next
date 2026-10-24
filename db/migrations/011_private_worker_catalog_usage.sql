-- The private worker reads the existing security-invoker classification view
-- only while scheduling tenant-scoped match jobs after a profile is ready.
GRANT USAGE ON SCHEMA catalog TO cb_private_worker;

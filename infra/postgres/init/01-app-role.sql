-- Local dev only (runs once, on a fresh volume). Production provisions roles via ops/IaC.
-- The application role must NOT be a superuser and must NOT have BYPASSRLS:
-- superusers bypass row-level security entirely, which would make every RLS policy decorative.
CREATE ROLE medpal_app LOGIN PASSWORD 'medpal_app' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;

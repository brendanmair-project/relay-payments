-- Runs once when the postgres volume is first created (REL-12): tests use relay_test, never relay.
CREATE DATABASE relay_test OWNER relay;

-- Owner-managed public cape catalog. No player identities or credentials live here.
CREATE TABLE IF NOT EXISTS cubeon_cosmetics (
    id text PRIMARY KEY CHECK (id ~ '^[a-z][a-z0-9_-]{2,63}$'),
    kind text NOT NULL DEFAULT 'cape' CHECK (kind IN ('cape', 'pet', 'wing', 'head', 'feet', 'aura')),
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
    description text NOT NULL DEFAULT '' CHECK (length(description) <= 400),
    mime_type text NOT NULL CHECK (mime_type IN ('image/png', 'image/gif', 'application/vnd.cubeon.cosmetic+json')),
    file_bytes bytea NOT NULL,
    byte_size integer NOT NULL CHECK (byte_size BETWEEN 1 AND 2097152),
    sha256 text NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    preview_png bytea NOT NULL CHECK (octet_length(preview_png) BETWEEN 1 AND 24576),
    published boolean NOT NULL DEFAULT true,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (octet_length(file_bytes) = byte_size),
    CHECK (encode(sha256(file_bytes), 'hex') = sha256)
);
-- Idempotent upgrade of the original cape-only table. Preserve all existing rows.
DO $$ BEGIN
ALTER TABLE cubeon_cosmetics DROP CONSTRAINT IF EXISTS cubeon_cosmetics_kind_check;
ALTER TABLE cubeon_cosmetics ADD CONSTRAINT cubeon_cosmetics_kind_check CHECK (kind IN ('cape', 'pet', 'wing', 'head', 'feet', 'aura'));
ALTER TABLE cubeon_cosmetics DROP CONSTRAINT IF EXISTS cubeon_cosmetics_mime_type_check;
ALTER TABLE cubeon_cosmetics ADD CONSTRAINT cubeon_cosmetics_mime_type_check CHECK (mime_type IN ('image/png', 'image/gif', 'application/vnd.cubeon.cosmetic+json'));
END $$;

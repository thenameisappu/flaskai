#!/bin/bash
# =============================================================================
#  Molecule Search API — Database Initialization
#  Reads MOLECULES_TABLE from environment (set via docker-compose env block)
# =============================================================================

set -e

TABLE="${MOLECULES_TABLE:-production_molecules}"

echo "================================================"
echo " Initializing database..."
echo "   Table: ${TABLE}"
echo "================================================"

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" \
     --dbname   "$POSTGRES_DB" \
     <<-EOSQL

-- ---------------------------------------------------------------------------
-- 1. Extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS rdkit;

-- ---------------------------------------------------------------------------
-- 2. Table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS "${TABLE}" (
    id                SERIAL   PRIMARY KEY,
    "structureMol"    mol,
    "casNumber"       TEXT,
    "alternativeNames" TEXT[]  DEFAULT '{}',
    cid               INTEGER,
    "iupacName"       TEXT,
    "molWeight"       FLOAT,
    "inchiKey"        TEXT
);

-- ---------------------------------------------------------------------------
-- 3. Indexes
-- ---------------------------------------------------------------------------

-- Substructure search (@>)
CREATE INDEX IF NOT EXISTS idx_mol_gist
    ON "${TABLE}" USING GIST ("structureMol");

-- Tanimoto similarity (tanimoto_sml + morgan_fp)
CREATE INDEX IF NOT EXISTS idx_mol_morgan_fp
    ON "${TABLE}" USING GIST (morgan_fp("structureMol"));

-- Exact match via InChIKey
CREATE INDEX IF NOT EXISTS idx_inchikey
    ON "${TABLE}" ("inchiKey");

-- CAS number (ILIKE pattern)
CREATE INDEX IF NOT EXISTS idx_casnumber
    ON "${TABLE}" ("casNumber" text_pattern_ops);

-- IUPAC name (lower() + LIKE pattern)
CREATE INDEX IF NOT EXISTS idx_iupacname_lower
    ON "${TABLE}" (lower("iupacName") text_pattern_ops);

-- Molecular weight range queries
CREATE INDEX IF NOT EXISTS idx_molweight
    ON "${TABLE}" ("molWeight");

-- CID lookup
CREATE INDEX IF NOT EXISTS idx_cid
    ON "${TABLE}" (cid);

-- alternativeNames array (GIN for unnest queries)
CREATE INDEX IF NOT EXISTS idx_altnames_gin
    ON "${TABLE}" USING GIN ("alternativeNames");

-- ---------------------------------------------------------------------------
-- 4. Verify
-- ---------------------------------------------------------------------------
DO \$\$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_extension WHERE extname = 'rdkit'
    ) THEN
        RAISE EXCEPTION 'RDKit extension is NOT installed.';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_tables WHERE tablename = '${TABLE}'
    ) THEN
        RAISE EXCEPTION 'Table ${TABLE} was not created.';
    END IF;

    RAISE NOTICE '================================================';
    RAISE NOTICE ' Init complete.';
    RAISE NOTICE '   Table   : ${TABLE}';
    RAISE NOTICE '   Indexes : 8 created';
    RAISE NOTICE '   RDKit   : OK';
    RAISE NOTICE '================================================';
END;
\$\$;

EOSQL

echo "Done."
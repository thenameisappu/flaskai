import os
import json
from db import get_connection
from rdkit import Chem
from rdkit.Chem.inchi import MolToInchiKey



def generate_inchikey(smiles):

    try:
        mol = Chem.MolFromSmiles(smiles)

        if mol is None:
            return None, "Invalid SMILES"

        inchikey = MolToInchiKey(mol)

        return inchikey, None

    except Exception as e:
        return None, str(e)


def insert_samples(json_file="molecules_100.json"):

    if not os.path.exists(json_file):
        print(f"JSON file not found: {json_file}")
        return

    with open(json_file, "r", encoding="utf-8") as f:
        samples = json.load(f)

    conn = get_connection()
    cur = conn.cursor()

    inserted = 0
    skipped = 0
    failed = 0

    for s in samples:

        try:

            smiles = s.get("smiles")

            if not smiles:
                print(f"Missing SMILES for CID {s.get('cid')}")
                failed += 1
                continue

            mol = Chem.MolFromSmiles(smiles)

            if mol is None:
                print(f"Invalid SMILES: {smiles}")
                failed += 1
                continue

            inchikey, error = generate_inchikey(smiles)

            if not inchikey:
                print(f"Error generating InChIKey for {smiles}: {error}")
                failed += 1
                continue

            cur.execute("""
                INSERT INTO molecules
                (cid, iupacname, casnumber, alternativenames, smiles, inchikey, molweight)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (cid) DO NOTHING
            """, (
                s.get("cid"),
                s.get("iupacName"),
                s.get("casNumber"),
                s.get("alternativeNames", []),
                smiles,
                inchikey,
                s.get("molWeight")
            ))

            if cur.rowcount == 0:
                skipped += 1
            else:
                inserted += 1

        except Exception as e:

            print(f"Error inserting {s.get('iupacName','Unknown')}: {e}")
            conn.rollback()
            failed += 1

    conn.commit()
    cur.close()
    conn.close()

    print("\nInsertion complete.")
    print(f"Inserted: {inserted}")
    print(f"Skipped: {skipped}")
    print(f"Failed: {failed}")


if __name__ == "__main__":
    insert_samples()
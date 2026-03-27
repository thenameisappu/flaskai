from db import get_connection


def clear_molecules_table():
    try:
        conn = get_connection()
        cur = conn.cursor()

        # ⚡ Delete all data and reset IDs
        cur.execute("TRUNCATE TABLE molecules RESTART IDENTITY CASCADE;")
        conn.commit()

        print("✅ Table 'molecules' cleared successfully.")

    except Exception as e:
        print(f"❌ Error clearing table: {e}")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    clear_molecules_table()
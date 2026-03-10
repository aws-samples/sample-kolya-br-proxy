#!/bin/bash
# Truncate all tables in the database
# Usage: ./scripts/clear_all_tables.sh

echo "⚠️  WARNING: This will delete ALL data from ALL tables!"
echo "Database: kbp"
echo "Host: 127.0.0.1:5432"
echo "User: root"
echo ""

# Get all table names
echo "Fetching table names..."
TABLES=$(PGPASSWORD=root psql -h 127.0.0.1 -U root -d kbp -t -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;")

if [ -z "$TABLES" ]; then
    echo "No tables found."
    exit 0
fi

echo "Found tables:"
echo "$TABLES" | sed 's/^/  - /'
echo ""

# Count tables
TABLE_COUNT=$(echo "$TABLES" | wc -l | tr -d ' ')
echo "Total: $TABLE_COUNT tables"
echo ""

# Truncate all tables
echo "Truncating all tables..."
PGPASSWORD=root psql -h 127.0.0.1 -U root -d kbp <<EOF
-- Disable foreign key checks
SET session_replication_role = 'replica';

-- Truncate each table
$(echo "$TABLES" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | awk '{print "TRUNCATE TABLE " $1 " CASCADE;"}')

-- Re-enable foreign key checks
SET session_replication_role = 'origin';
EOF

echo ""
echo "✅ All tables truncated successfully!"
echo ""

# Verify tables are empty
echo "Verifying tables are empty:"
for table in $TABLES; do
    table=$(echo $table | tr -d ' ')
    count=$(PGPASSWORD=root psql -h 127.0.0.1 -U root -d kbp -t -c "SELECT COUNT(*) FROM $table;")
    echo "  $table: $count rows"
done

echo ""
echo "Done!"

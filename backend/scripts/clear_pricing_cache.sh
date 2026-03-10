#!/bin/bash
# Clear pricing table cache
# Usage: ./scripts/clear_pricing_cache.sh [TOKEN]

if [ -z "$1" ]; then
    echo "Usage: $0 <JWT_TOKEN>"
    echo ""
    echo "Example:"
    echo "  $0 eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    exit 1
fi

TOKEN="$1"

echo "Clearing pricing cache..."
curl -X POST "http://localhost:8000/admin/monitor/clear-cache" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json"

echo ""
echo ""
echo "✅ Cache cleared! Refresh the frontend page to see empty table."

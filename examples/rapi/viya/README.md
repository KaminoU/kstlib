# SAS Viya - RAPI Proof of Concept

This directory contains a **proof of concept** demonstrating how kstlib RAPI handles large-scale, nested REST API definitions in declarative YAML format.

## What This Is

This collection (~1250 endpoints) was created to **validate RAPI's architecture**:

- Nested YAML includes (`include:` directive)
- Multi-level API organization (root → sub-modules)
- Service-level vs endpoint-level configuration inheritance
- Large-scale endpoint management with filtering and search

**This is NOT a validated API reference.** Body schemas were AI-generated and may contain errors.

## What Works Reliably

| Aspect | Status |
|--------|--------|
| Endpoint paths, methods, descriptions | Accurate (from SAS docs) |
| YAML structure and includes | Validated |
| CLI filtering and search | Validated |
| Body schemas | **Approximate - NOT validated** |

## Example Usage

```bash
# List all endpoints
kstlib rapi list

# Filter by API or method
kstlib rapi list --filter "reports POST"
kstlib rapi list --filter "modelRepository"

# Show endpoint details
kstlib rapi show reports.reports-create

# Execute with query parameters (key=value)
kstlib rapi reports.reports-list limit=5

# POST with JSON body
kstlib rapi reports.reports-create -b '{"name": "My Report"}'

# POST with body from file
kstlib rapi reports.reports-create -b @payload.json

# Custom headers
kstlib rapi reports.reports-list -H "X-Custom: value"

# Quiet mode (JSON only, for scripting)
kstlib rapi reports.reports-list -q
```

## Next Steps

A separate repository (`viyapi`) may be created to:

1. Validate all body schemas against [official SAS documentation](https://developer.sas.com/rest-apis/)
2. Provide a production-ready SAS Viya API collection
3. Accept community contributions for schema accuracy

## RAPI Convention Reminder

- Required fields: `fieldName*: null`
- Optional fields: `fieldName: null`
- Arrays: show ONE example item with all fields
- Binary/raw content: `body: null` with appropriate `Content-Type` header

## License

SAS Viya is a trademark of SAS Institute Inc.

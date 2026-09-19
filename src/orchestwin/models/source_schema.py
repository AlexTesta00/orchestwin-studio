"""Share identical manifest field schemas without weakening any constraint."""


def share_manifest_field_schemas(schema):
    definitions = schema.get("$defs", {})
    checks = [
        value
        for name, value in definitions.items()
        if name.startswith("ApprovedStatementCheck")
        and name.removeprefix("ApprovedStatementCheck").isdigit()
    ]
    if len(checks) < 2:
        return
    for field, name in (
        ("public_interface", "ManifestPublicInterface"),
        ("observable_postcondition", "ManifestPostcondition"),
    ):
        fields = [check.get("properties", {}) for check in checks]
        original = fields[0].get(field)
        if original is None or any(item.get(field) != original for item in fields):
            continue
        if name in definitions:
            raise ValueError("manifest shared schema name collision")
        definitions[name] = original
        for item in fields:
            item[field] = {"$ref": f"#/$defs/{name}"}

"""Texte von außen (Quellen, Sprachmodelle) so bereinigen, dass sie sich als UTF-8 schreiben lassen.

Ein einzelnes Surrogat, etwa ein halbes Emoji, liefert `json.loads` klaglos; Merken, Hash,
Report und Suchprofil scheitern dann mit `UnicodeEncodeError`.
"""


def encodable(text: str) -> str:
    """Der Text mit "?" statt einzelner Surrogate."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return text.encode("utf-8", "replace").decode("utf-8")
    return text  # der Normalfall, ohne Kopie


def encodable_data(data: object) -> object:
    """`encodable` für jeden Text in verschachtelten Listen und dicts (Werte und Schlüssel)."""
    if isinstance(data, str):
        return encodable(data)
    if isinstance(data, list):
        return [encodable_data(entry) for entry in data]
    if isinstance(data, dict):
        return {encodable_data(key): encodable_data(value) for key, value in data.items()}
    return data

import yaml


def load_seed_companies(path: str) -> list[str]:
    with open(path) as f:
        data = yaml.safe_load(f)
    if not data:
        return []
    return data.get("companies", [])

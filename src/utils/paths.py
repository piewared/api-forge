def make_postgres_url(
    user: str, password: str, host: str, port: int, dbname: str
) -> str:
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

from enterprise_document_rag import __version__


def test_version_matches_project_metadata() -> None:
    assert __version__ == "0.1.0.dev0"

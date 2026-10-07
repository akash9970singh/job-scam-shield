from app.env import load_env


def test_load_env_reads_file_without_overriding(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n\nJSS_TEST_A=from-file\nJSS_TEST_B = \"quoted value\"\nJSS_TEST_C=from-file\nnot a setting\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("JSS_TEST_A", raising=False)
    monkeypatch.delenv("JSS_TEST_B", raising=False)
    monkeypatch.setenv("JSS_TEST_C", "already-set")

    load_env(env_file)

    import os
    assert os.environ["JSS_TEST_A"] == "from-file"
    assert os.environ["JSS_TEST_B"] == "quoted value"
    assert os.environ["JSS_TEST_C"] == "already-set"  # real environment wins
    for key in ("JSS_TEST_A", "JSS_TEST_B"):
        monkeypatch.delenv(key)


def test_missing_env_file_is_fine(tmp_path):
    load_env(tmp_path / "does-not-exist")

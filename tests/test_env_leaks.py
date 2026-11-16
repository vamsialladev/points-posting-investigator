"""The .env leak scanner: finds values by name only, and a scan of nothing is NOT RUN, never a pass (rule 7)."""

import subprocess
from pathlib import Path

from app import env_leaks
from app.env_leaks import NOT_RUN, find_leaks, main, secret_values


def git_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    if files:
        subprocess.run(["git", "add", *files], cwd=tmp_path, check=True)
    return tmp_path


def test_secret_values_skip_short_unchanged_and_non_secret_names():
    values = {
        "APP_SECRET_KEY": "a-real-local-secret-value-1234567890",
        "LEDGER_API_TOKEN": "short",
        "LOG_LEVEL": "INFO-but-long-enough",
        "POSTGRES_PASSWORD": "same-as-template",
        "SOME_NEW_TOKEN": "looks-like-a-token-123",
    }
    template = {"POSTGRES_PASSWORD": "same-as-template"}
    assert set(secret_values(values, template)) == {"APP_SECRET_KEY", "SOME_NEW_TOKEN"}


def test_find_leaks_reports_file_and_name(tmp_path):
    leaky = tmp_path / "notes.md"
    leaky.write_text("oops: a-real-local-secret-value-1234567890\n", encoding="utf-8")
    clean = tmp_path / "clean.md"
    clean.write_text("nothing here\n", encoding="utf-8")
    leaks = find_leaks({"APP_SECRET_KEY": "a-real-local-secret-value-1234567890"}, [leaky, clean, tmp_path / "gone"])
    assert leaks == [(str(leaky), "APP_SECRET_KEY")]


def test_no_env_file_is_not_run_and_fails(tmp_path, capsys):
    git_repo(tmp_path, {"README.md": "hello\n"})
    assert main(tmp_path) == NOT_RUN != 0
    assert "NOT RUN" in capsys.readouterr().out


def test_env_without_secret_values_is_not_run(tmp_path, capsys):
    git_repo(tmp_path, {"README.md": "hello\n"})
    (tmp_path / ".env").write_text("LOG_LEVEL=INFO\nAPP_SECRET_KEY=\n", encoding="utf-8")
    assert main(tmp_path) == NOT_RUN
    assert "nothing was checked" in capsys.readouterr().out


def test_no_tracked_files_is_not_run(tmp_path, capsys):
    git_repo(tmp_path, {})
    (tmp_path / ".env").write_text("APP_SECRET_KEY=a-real-local-secret-value-1234567890\n", encoding="utf-8")
    assert main(tmp_path) == NOT_RUN
    assert "tracks no files" in capsys.readouterr().out


def test_a_leak_fails_and_prints_the_name_not_the_value(tmp_path, capsys):
    secret = "a-real-local-secret-value-1234567890"
    git_repo(tmp_path, {"config.md": f"key = {secret}\n"})
    (tmp_path / ".env").write_text(f"APP_SECRET_KEY={secret}\n", encoding="utf-8")
    assert main(tmp_path) == 1
    out = capsys.readouterr().out
    assert "APP_SECRET_KEY" in out and "config.md" in out
    assert secret not in out


def test_clean_repo_passes_and_says_how_much_it_checked(tmp_path, capsys):
    git_repo(tmp_path, {"README.md": "hello\n"})
    (tmp_path / ".env").write_text("APP_SECRET_KEY=a-real-local-secret-value-1234567890\n", encoding="utf-8")
    assert main(tmp_path) == 0
    assert "Checked 1 secret value(s) from .env against 1 tracked file(s): 0 leak(s)." in capsys.readouterr().out


def test_tracked_files_lists_only_git_files(tmp_path):
    git_repo(tmp_path, {"a.md": "a\n"})
    (tmp_path / "untracked.md").write_text("b\n", encoding="utf-8")
    assert [p.name for p in env_leaks.tracked_files(tmp_path)] == ["a.md"]

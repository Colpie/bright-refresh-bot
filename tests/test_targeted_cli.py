from click.testing import CliRunner
from src.main import cli


def test_targeted_run_rejects_resume_before_api_calls():
    result = CliRunner().invoke(cli, ['run', '--vacancy-id', '93833', '--resume', 'older'])
    assert result.exit_code == 2
    assert 'cannot combine' in result.output


def test_zero_limit_cannot_accidentally_start_full_run():
    result = CliRunner().invoke(cli, ['run', '--limit', '0'])
    assert result.exit_code == 2


def test_targeted_run_rejects_multiple_vacancies():
    result = CliRunner().invoke(cli, ['run', '--vacancy-id', '93833', '--limit', '2'])
    assert result.exit_code == 2

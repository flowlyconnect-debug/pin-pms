from __future__ import annotations


def pytest_configure(config) -> None:
    args = [str(arg) for arg in config.invocation_params.args]
    running_integration = any("tests/integration" in arg.replace("\\", "/") for arg in args)
    if not running_integration:
        return

    # Integration acceptance tests are executed as a separate CI job and should
    # not inherit unit-test coverage gates from the global addopts.
    config.option.no_cov = True
    config.option.cov_fail_under = 0

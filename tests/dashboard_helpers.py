def finish_scan(app):
    """Wait for the finite background job, then render its terminal UI state."""
    try:
        job = app.session_state["scan_job"]
    except KeyError:
        return app
    if not job.join(10):
        raise AssertionError("Dashboard scan did not finish")
    return app.run()

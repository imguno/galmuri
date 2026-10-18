"""The standalone default process is also an App-aware built-in binding."""


def process_default(file):
    from galmuri.processing.pipeline import Pipeline

    return Pipeline.default()(file)

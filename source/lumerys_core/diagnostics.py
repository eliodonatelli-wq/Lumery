"""Privacy-preserving diagnostics: structural stack only, never exception text."""
import logging
import platform
from . import __version__


def format_error(exc, stage):
    # Do not format exception messages, source lines, locals, paths, or OS hostnames.
    system = platform.system()
    system = system if system in ('Darwin', 'Windows', 'Linux') else 'Other'
    lines = [f'Lumerys {__version__} | OS: {system} | stage: {stage}',
             'Traceback (sanitized; messages and paths omitted):']
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        tb = exc.__traceback__
        while tb is not None:
            module = tb.tb_frame.f_globals.get('__name__', '')
            if module == 'lumerys_core' or module.startswith('lumerys_core.'):
                lines.append(f'  {module}, line {tb.tb_lineno}')
            else:
                lines.append(f'  <external frame>, line {tb.tb_lineno}')
            tb = tb.tb_next
        # Exception class names are included only for trusted module namespaces.
        cls = type(exc)
        trusted = cls.__module__ == 'builtins' or cls.__module__.startswith(('lumerys_core', 'numpy', 'scipy', 'astropy', 'PyQt6'))
        lines.append(cls.__name__ if trusted else 'ExternalError')
        exc = exc.__cause__ if exc.__cause__ is not None else (None if exc.__suppress_context__ else exc.__context__)
        if exc is not None:
            lines.append('Caused by/context:')
    return '\n'.join(lines)


def log_report(ctx, report):
    try:
        sink = getattr(ctx, 'log', None)
        if callable(sink):
            sink(report)
            return
    except Exception:
        pass
    # Do not create files or let a failed log sink interrupt processing.
    try:
        logging.getLogger('lumerys').error('%s', report)
    except Exception:
        pass


def report_error(ctx, exc, stage):
    log_report(ctx, format_error(exc, stage))

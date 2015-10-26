"""Configuration"""
import os
from flask.ext.script import Server


class BaseConfig(object):
    """Base configuration - override in subclasses"""
    PROJECT = "portal"
    PROJECT_ROOT =\
            os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    DEBUG = False
    DEFAULT_MAIL_SENDER = 'dontreply@truenth-demo.cirg.washington.edu'
    LOG_FOLDER = os.path.join('/var/log', __package__)
    LOG_LEVEL = 'DEBUG'
    OAUTH2_PROVIDER_TOKEN_EXPIRES_IN = 60 * 60  # units: seconds
    TESTING = False
    SECRET_KEY = 'override this secret key'
    USER_UNAUTHORIZED_ENDPOINT = 'portal.index'
    USER_UNAUTHENTICATED_ENDPOINT = 'portal.index'


class DefaultConfig(BaseConfig):
    """Default configuration"""
    DEBUG = True
    SQLALCHEMY_ECHO = False


class TestConfig(BaseConfig):
    """Testing configuration - used by unit tests"""
    TESTING = True
    SQLALCHEMY_ECHO = False
    SQLALCHEMY_DATABASE_URI = 'sqlite://'
    WTF_CSRF_ENABLED = False


from flask import Config
def early_app_config_access():
    """Workaround to bootstrap configuration problems

    Some extensions require config values before the flask app can be
    initialized.  Expose the same configuration used by the app by
    direct access.

    Avoid use of this approach, as the app has its own config with a
    chain of overwrites.  i.e. use app.config whenever possible.

    """
    _app_config = Config(None)
    _app_config.from_pyfile(os.path.join(\
            os.path.dirname(__file__), 'application.cfg'))
    return _app_config


class ConfigServer(Server):
    """Correctly read Flask configuration values when running Flask

    Flask-Script 2.0.5 does not read host and port specified in
    SERVER_NAME.  This subclass fixes that.

    Bug: https://github.com/smurfix/flask-script/blob/7dfaf2898d648761632dc5b3ba6654edff67ec57/flask_script/commands.py#L343

    Values passed in when instance is called as a function override
    those passed during initialization which override configured values

    See https://github.com/smurfix/flask-script/issues/108
    """
    def __init__(self, port=None, host=None, **kwargs):
        """Override default port and host

        Allow fallback to configured values

        """
        super(ConfigServer, self).__init__(port=port, host=host, **kwargs)

    def __call__(self, app=None, host=None, port=None, *args, **kwargs):
        """Call app.run() with highest precedent configuration values"""
        # Fallback to initialized value if None is passed
        port = self.port if port is None else port
        host = self.host if host is None else host
        super(ConfigServer, self).__call__(app=app, host=host,
                port=port, *args, **kwargs)


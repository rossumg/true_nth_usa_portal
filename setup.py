""" setup script for 'portal' package

for development:
    python setup.py develop

to install:
    python setup.py install

"""

from setuptools import setup

project = "portal"

# maintain long_description as a single long line.
# workaround for a bug in pkg_info._get_metadata('PKG-INFO')
long_description =\
"""Alpha version of the TrueNTH Central Services RESTful API, to be used by TrueNTH intervention applications. This API attempts to conform with the HL7 FHIR specification as much as is reasonable.
"""

setup(
    name=project,
    url='https://github.com/uwcirg/true_nth_usa_portal_demo',
    description='TrueNTH Central Services',
    long_description=long_description,
    author='University of Washington',
    packages=["portal"],
    include_package_data=True,
    use_scm_version=True,
    setup_requires=['setuptools_scm'],
    zip_safe=False,
    dependency_links=[
        "git+https://github.com/pbugni/Flask-User.git#egg=Flask-User-0.6.8.1",
    ],
    install_requires=[
        'Authomatic>=0.1.0',
        'celery',
        'coverage',
        'Flask>=0.10.1',
        'Flask-Babel',
        'Flask-Celery-Helper',
        'Flask-Migrate',
        'Flask-OAuthlib',
        'Flask-SQLAlchemy',
        'Flask-Script',
        'Flask-Swagger',
        'Flask-Testing',
        'Flask-User>=0.6.8.1',
        'Flask-WebTest',
        'jsonschema',
        'nose',
        'oauthlib',
        'page_objects',
        'pkginfo',
        'psycopg2',
        'python-dateutil',
        'recommonmark',
        'redis',
        'selenium',
        'sphinx',
        'sphinx_rtd_theme',
        'swagger_spec_validator',
        'validators',
        'xvfbwrapper',
    ],
    test_suite='tests',
    classifiers=[
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'Intended Audience :: Healthcare Industry',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Scientific/Engineering :: Bio-Informatics',
        'Topic :: Scientific/Engineering :: Medical Science Apps',
    ]
)

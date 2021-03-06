Docker
************

.. contents::
   :depth: 3
   :local:

Background
==========

Docker is an open-source project that can be used to automate the deployment of applications inside software containers. Docker defines specifications and provides tools that can be used to automate building and deploying software containers.

Dockerfiles declaratively define how to build a Docker :term:`image` that is subsequently run as a :term:`container`, any number of times. Configuration in Dockerfiles is primarily driven by image build-time arguments (``ARG``) and environment variables (``ENV``) that may be overridden.

Docker-compose (through ``docker-compose.yaml``) defines the relationship (exposed ports, volume mappings) between the Shared Services web container and the other services it depends on (redis, postgresql).

Getting Started
===============
Install `docker-compose` as per environment.  For example, from a debian system::

    # add user to docker group
    sudo usermod -aG docker $USER
    sudo pip install docker_compose

.. note::
    A clean environment and fresh git checkout are recommended, but not required

Copy and edit the default environment file (from the project root)::

    cp docker/portal.env.default docker/portal.env
    # update SERVER_NAME to include port if not binding with 80/443
    # SERVER_NAME=localhost:8080

.. note::
    All docker-compose commands are run from the ``docker/`` directory

Download and run the ``latest`` images::

    docker-compose pull web
    docker-compose up web

By default, the ``truenth_portal`` image with the ``latest`` tag is downloaded and used. To use an image with another tag, set the ``DOCKER_IMAGE_TAG`` environment variable::

    export DOCKER_IMAGE_TAG='stable'
    docker-compose pull web
    docker-compose up web

Docker Images
=============

Two Dockerfiles (``Dockerfile.build`` and ``Dockerfile``) define how to build a docker image capable of creating a Debian package from the portal codebase, and how to install and configure the package into a working Shared Services instance.

Building a Debian Package
-------------------------

To build a Debian package from the current branch of your local repo::

    # Build debian package from current local branch
    docker-compose -f docker-compose.build.yaml run builder

If you would like to create a package from a remote repository you can override the local repo as follows below::

    # Override default with environment variable
    export GIT_REPO='https://github.com/USERNAME/true_nth_usa_portal'

    # Build the package from the above repo
    docker-compose -f docker-compose.build.yaml run builder

Building a Shared Services Docker Image
---------------------------------------

If you would like to build a Shared Services image, follow the instructions in `Building a Debian Package`_, and run the following docker-compose commands::

    # Override default (Artifactory) docker repo to differentiate locally-built images
    export DOCKER_REPOSITORY=''

    # Build the "web" image locally
    docker-compose build web

    docker-compose up web

Advanced Usage
==============

Running in Background
---------------------
Docker-compose services can be run in the background by adding the ``--detach`` option. Services started in detached mode will run until stopped or killed.:

    # Start the "web" service (and dependencies) in background
    docker-compose up --detach web

Viewing Logs
------------
Docker-compose will only show logs of the requested services (usually ``web``), when not run in the background. To view the logs of all running services:

    # Tail and follow logs of all services
    docker-compose logs --follow

    # Tail and follow logs of a specific service
    docker-compose logs --follow celerybeat

PostgreSQL Access
-----------------
To interact with the running database container, started via the ``docker-compose`` instructions above, use ``docker exec`` as follows below::

    docker-compose exec db psql --username postgres

Account Bootstrapping
---------------------
To bootstrap an admin account after a fresh install, run the below ``flask`` CLI command::

    docker-compose exec web \
        flask add_user \
            --email 'admin_email@example.com' \
            --password 'exampleP@$$W0RD' \
            --role admin

Advanced Configuration
======================

Environment variables defined in the ``portal.env`` environment file are only passed to the underlying containers. However, some environment variables are used for configuration specific to docker-compose.

An
`additional environment file <https://docs.docker.com/compose/environment-variables/#the-env-file>`__, specifically named ``.env``, in the current working directory can define environment variables available through the entire docker-compose file (including containers). These docker-compose-level environment variables can also be set in the shell invoking docker-compose.

One use for environmental variables defined in the ``.env`` file is overriding the default ``COMPOSE_PROJECT_NAME`` which can be used to namespace multiple deployments running on the same host. In production deployments ``COMPOSE_PROJECT_NAME`` is set to correspond to the domain being served.

Continuous Delivery
===================

Our continuous integration setup leverages TravisCI's docker support and deployment integration to create and deploy Debian packages and Docker images for every commit.

Packages and images are built in a separate :term:`job` (named ``build-artifacts``) that corresponds with a tox environment that does nothing and that's allowed to fail without delaying the build or affecting its status.

If credentials are configured, packages and images will be uploaded to their corresponding repository after the build process. Otherwise, artifacts will only be built, but not uploaded or deployed.

Currently, our TravisCI setup uses packages locally-built on TravisCI instead of pushing, then pulling from our Debian repository. This may lead to non-deterministic builds and should probably be reconciled at some point, ideally using
`TravisCI build stages <https://docs.travis-ci.com/user/build-stages>`__.


Configuration
-------------

Most if not all values needed to build and deploy Shared Services are available as environment variables with sane, CIRG-specific defaults. Please see the `global section of .travis.yml <https://docs.travis-ci.com/user/environment-variables#global-variables>`_.

.. glossary::

    image
        Docker images are the basis of containers. An Image is an ordered collection of root filesystem changes and the corresponding execution parameters for use within a container runtime. An image typically contains a union of layered filesystems stacked on top of each other. An image does not have state and it never changes.

    container
        A container is a runtime instance of a docker image.
        A Docker container consists of:
        * A Docker image
        * Execution environment
        * A standard set of instructions

    environment file
        A file for defining environment variables. One per line, no shell syntax (export etc).

    build
        A group of TravisCI jobs tied to a single commit; initiated by a pull request or push

    job
        A discrete unit of work that is part of a build. All jobs part of a build must pass for the build to pass (unless a job is set as an `allowed failure <https://docs.travis-ci.com/user/customizing-the-build#rows-that-are-allowed-to-fail>`_).


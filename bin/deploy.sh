#!/bin/sh -e

cmdname=$(basename $0)

usage() {
    cat << USAGE >&2
Simple script to make deployments of fresh code a one-command operation"
Usage:
    $cmdname [-b <branch>] [-p <path>]
    -b     Remote branch to checkout (default: develop)
    -p     Path to repository (default: current working directory)
USAGE
    exit 1
}

update_repo(){
    echo "Updating repository"

    git fetch origin
    git fetch --tags

    if [ "$BRANCH" != "$(git rev-parse --abbrev-ref HEAD)" ]; then
        git checkout "$BRANCH"
    fi

    git pull origin "$BRANCH"
}

repo_path=$( cd $(dirname $0) ; git rev-parse --show-toplevel )

while getopts ":b:p:" option; do
    case "${option}" in
        b)
            branch=${OPTARG}
            ;;
        p)
            repo_path=${OPTARG}
            ;;
        *)
            usage
            ;;
    esac
done
shift $((OPTIND-1))

if [ ! -d "$repo_path/.git" ]; then
    echo 'Error: Bad git repo path' >&2
    exit 1
fi

export GIT_WORK_TREE="$repo_path"
export GIT_DIR="${GIT_WORK_TREE}/.git"
export FLASK_APP="${GIT_WORK_TREE}/manage.py"

# Assign branch in the following precedence: $BRANCH, $branch, "develop"
BRANCH=${BRANCH:-${branch:-develop}}

update_repo

echo "Activating virtualenv"
. "${GIT_WORK_TREE}/env/bin/activate"

echo "Updating python dependancies"
cd "${GIT_WORK_TREE}"
env --unset GIT_WORK_TREE pip install --quiet --requirement requirements.txt

echo "Synchronizing database"
flask sync

echo "Updating package metadata"
python setup.py egg_info --quiet

# Restart apache if application is served by apache
if [ "${GIT_WORK_TREE}" == "/srv/www/"* ]; then
    echo "Restarting services"
    sudo service apache2 restart
    sudo service celeryd restart
fi

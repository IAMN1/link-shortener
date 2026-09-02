# The entry point for the `flask` command.
#
# It lives here rather than in an env file because it is neither a secret
# nor a choice: the factory is where it is, whatever the deployment. Flask
# reads `.flaskenv` on every run, before any `.env`, so the project's
# command groups are registered even when no env file exists yet.
#
# That last part is the whole reason this file was added. `FLASK_APP` used
# to be named only in `.env`, and the Docker path never creates `.env` --
# it creates `.env.docker`. So the second command of that path,
#
#     flask security generate-secrets --write .env.docker
#
# answered `Error: No such command 'security'`. With no FLASK_APP there is
# no application, with no application none of `security`, `db`, `alembic`,
# `link`, `cache`, `maintenance`, `stats`, `create-admin` or `create-user`
# is registered, and the message names the symptom rather than the cause.
# Measured by walking the README's Docker column on a fresh clone.
#
# An env file may still override it: Flask loads `.env` as well, and a
# value already in the environment wins. Nothing in `src` reads this
# variable -- it is read by the `flask` executable itself.
FLASK_APP=link_shortener.web.app_factory:create_app

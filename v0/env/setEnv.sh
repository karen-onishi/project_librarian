#!/bin/bash
# adk env
export PROJECT_ID=d001-000-chiel-dev
export LOCATION=us-central1
# export LOG_LEVEL=DEBUG
export LOG_LEVEL=ERROR
export IS_LOCAL=false
export PROJECT_LIBRARIAN_REASONING_ENGINE_ID=4566541170502533120

## agent
# export TASK_ANALYZER_AGENT_MODEL=gemini-2.5-flash
# export PROJECT_ANALYZER_AGENT_MODEL=gemini-2.5-flash
# export ADVICE_GENERATOR_AGENT_MODEL=gemini-2.5-flash
# export PLANNING_AGENT_MODEL=gemini-2.5-flash
# export GOOGLE_SEARCH_AGENT_MODEL=gemini-2.5-flash
# export URL_CONTEXT_AGENT_MODEL=gemini-2.5-flash
# export PROACTIVE_ADVISOR_MODEL=gemini-2.5-flash
export ENTITY_MANAGER_MODEL=gemini-2.5-flash
export PROJECT_ARCHIVIST_AGENT_MODEL=gemini-2.5-flash

## firestore
export FIRESTORE_DB_NAME="(default)"

## deploy
export STAGING_BUCKET_NAME=project-librarian-engine-staging-d001-000-chiel-dev
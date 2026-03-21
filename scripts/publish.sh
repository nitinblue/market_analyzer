#!/bin/bash
# Publish market_analyzer to PyPI
# Run: bash scripts/publish.sh [test|prod]

set -e

MODE=${1:-test}

echo "Building..."
python -m build

if [ "$MODE" = "test" ]; then
    echo "Uploading to TestPyPI..."
    twine upload --repository testpypi dist/*
    echo "Test install: pip install -i https://test.pypi.org/simple/ market-analyzer"
elif [ "$MODE" = "prod" ]; then
    echo "Uploading to PyPI..."
    twine upload dist/*
    echo "Install: pip install market-analyzer"
else
    echo "Usage: bash scripts/publish.sh [test|prod]"
fi

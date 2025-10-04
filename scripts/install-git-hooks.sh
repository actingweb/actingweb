#!/bin/bash
# Script to install git hooks for ActingWeb development

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
HOOKS_DIR="$PROJECT_ROOT/.git/hooks"

echo "Installing git hooks..."

# Create hooks directory if it doesn't exist
mkdir -p "$HOOKS_DIR"

# Install pre-commit hook
cat > "$HOOKS_DIR/pre-commit" << 'EOF'
#!/bin/bash
# Pre-commit hook to regenerate docs/requirements.txt from Poetry dependencies

# Check if pyproject.toml has been modified
if git diff --cached --name-only | grep -q "pyproject.toml"; then
    echo "pyproject.toml modified, regenerating docs/requirements.txt..."

    # Export dependencies with docs group
    poetry export --with docs --without-hashes -o docs/requirements.txt

    if [ $? -eq 0 ]; then
        # Add the updated requirements.txt to the commit
        git add docs/requirements.txt
        echo "✓ docs/requirements.txt updated and staged"
    else
        echo "✗ Failed to export dependencies"
        exit 1
    fi
fi

exit 0
EOF

chmod +x "$HOOKS_DIR/pre-commit"

echo "✓ Git hooks installed successfully"
echo ""
echo "Hooks installed:"
echo "  - pre-commit: Auto-regenerate docs/requirements.txt when pyproject.toml changes"

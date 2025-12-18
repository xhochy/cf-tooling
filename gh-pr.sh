#!/usr/bin/env bash
# Compatible with both Bash and Zsh

gh-pr() {
    # Check if a URL was provided
    if [ -z "$1" ]; then
        echo "Error: Please provide a GitHub PR URL"
        echo "Usage: gh-pr https://github.com/owner/repo/pull/123"
        return 1
    fi

    local url="$1"

    # Strip fragment (everything from # onwards)
    # Zsh requires escaping #, Bash does not
    if [ -n "$BASH_VERSION" ]; then
        url="${url%%#*}"
    else
        url="${url%%\#*}"
    fi

    # Extract owner, repo, and PR number from URL
    # Expected format: https://github.com/owner/repo/pull/123
    if [[ ! "$url" =~ ^https://github\.com/([^/]+)/([^/]+)/pull/([0-9]+)$ ]]; then
        echo "Error: Invalid GitHub PR URL format"
        echo "Expected: https://github.com/owner/repo/pull/123"
        return 1
    fi

    # Handle both Bash (BASH_REMATCH) and Zsh (match) regex capture arrays
    local owner repo pr_number
    if [ -n "$BASH_VERSION" ]; then
        owner="${BASH_REMATCH[1]}"
        repo="${BASH_REMATCH[2]}"
        pr_number="${BASH_REMATCH[3]}"
    else
        owner="${match[1]}"
        repo="${match[2]}"
        pr_number="${match[3]}"
    fi

    # Check if the repository folder exists
    if [ ! -d "$repo" ]; then
        gh repo fork "$owner/$repo" --clone=true
        if [ $? -ne 0 ]; then
            return 1
        fi
    fi

    # Change into the repository directory
    cd "$repo" || {
        return 1
    }

    # Fetch all updates from upstream
    git fetch -a upstream
    if [ $? -ne 0 ]; then
        :
    fi

    # Checkout the PR
    gh pr checkout "$pr_number"
    if [ $? -ne 0 ]; then
        return 1
    fi

    echo "Successfully checked out PR #$pr_number"
}

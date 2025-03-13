# ADR 0001: GitHub Suggestions for Code Review

## Status

Proposed

## Context

Currently, when reviewing code changes, the agent provides a single comment at the end of the PR with a diff and summary. To improve the review experience, we want to add inline suggestions directly on the code changes, similar to how human reviewers can suggest changes in GitHub's interface.

## Requirements

1. Parse a git diff into a structured object that can be processed programmatically
2. Use GitHub's API to post inline suggestions on specific lines of code in a PR
3. Port existing Go implementation from [greetings-api](https://github.com/kpenfound/greetings-api/blob/main/.dagger/main.go#L200) to Python

## Proposed Solutions

### 1. Git Diff Parser

**Description**: Create a Python tool to parse git diffs into a structured object
**Components**:

- Use `gitpython` library to read diff information
- Create data models to represent:
  - File changes
  - Line additions/deletions
  - Line numbers
  - Content changes
**Dependencies**:
- gitpython
- pydantic (for data models)

### 2. GitHub API Client

**Description**: Create a Python client for GitHub's API to post inline suggestions
**Components**:

- Implement GitHub API authentication
- Create methods for:
  - Reading PR information
  - Posting inline comments
  - Managing review sessions
**Dependencies**:
- PyGithub or GitHub API client library
- Environment variables for GitHub tokens

## Implementation Order

1. Git Diff Parser (Easier to implement first)
   - Can be developed and tested independently
   - No external API dependencies
   - Foundation for the GitHub integration
   - Can be used for other features in the future

2. GitHub API Client
   - Depends on the diff parser
   - Requires GitHub API access and authentication
   - More complex due to API rate limits and error handling

## Technical Considerations

1. **Authentication**:
   - Need to handle GitHub tokens securely
   - Consider using GitHub App authentication for better security

2. **Rate Limiting**:
   - GitHub API has rate limits
   - Need to implement retry logic and rate limit handling

3. **Error Handling**:
   - Handle network issues
   - Handle API errors gracefully
   - Provide meaningful error messages

4. **Testing**:
   - Unit tests for diff parser
   - Integration tests for GitHub API client
   - Mock GitHub API responses for testing

## Alternatives Considered

1. **Using Existing Libraries**:
   - Could use existing diff parsing libraries
   - Could use existing GitHub API clients
   - However, custom implementation gives us more control and better integration

2. **Different API Approach**:
   - Could use GitHub's GraphQL API instead of REST
   - Could use webhooks for real-time updates
   - However, REST API is simpler and sufficient for our needs

## Decision

We will implement this feature in two phases:

1. First, create the git diff parser as it's self-contained and can be tested independently
2. Then, implement the GitHub API client to post suggestions

This approach allows us to:

- Get early feedback on the diff parsing logic
- Test the core functionality independently
- Reduce complexity in the initial implementation
- Have a working foundation before adding API integration

## Consequences

### Positive

- Better code review experience with inline suggestions
- More interactive and detailed feedback
- Easier to understand and apply suggested changes

### Negative

- Additional complexity in the codebase
- Need to maintain GitHub API integration
- Potential rate limiting issues with GitHub API
- Need to handle various edge cases in diff parsing

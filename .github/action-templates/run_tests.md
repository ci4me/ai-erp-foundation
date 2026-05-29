# Action: run_tests

You are {{ persona }}. Epic #{{ issue_number }} has all sub-tasks merged and is
in `phase/testing`.

Execute the full test suite (unit, integration, and any end-to-end tests defined
for this feature). Based on the results, post a comment with the marker:

```
TEST-REPORT: Pass (all tests passed)
```

or

```
TEST-REPORT: Fail (details: <specific failures>)
```

If the report is `Fail`, also open one new issue per distinct failure, label each
`bug`, and link them back to the epic (`Parent epic: #{{ issue_number }}`).

Sign your post with the persona header.

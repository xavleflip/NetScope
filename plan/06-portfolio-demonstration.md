# Part 6: Prepare the portfolio demonstration

## Goal

Show a reproducible local demonstration and explain what the project proves
and what it does not.

## Tasks

- [ ] Start a controlled local HTTP server bound to `127.0.0.1`, from an empty folder.
- [ ] Scan its port and show the successful connection.
- [ ] Stop the server and repeat the scan to demonstrate the changed outcome.
- [ ] Add a screenshot using only reviewed local demonstration data.
- [ ] Add a reviewed example JSON report without sensitive machine information.
- [ ] Document architecture, limitations, and what you learned.
- [ ] Include reproducible demonstration steps in the README.

## Completion check

Someone can reproduce the demonstration using the README. Screenshots and
example reports match the implemented behavior and contain no sensitive data.
Explain any timeout rather than assuming every stopped service produces an
immediate refusal on every operating system.

## Verification

Follow the demonstration steps from start to finish, check the screenshot and
report against the actual results, and stop the temporary server afterward.
Explain that an open port is not automatically a vulnerability and that service
labels do not identify the software actually running.

## Scope

Keep external scanning, exploitation, and public deployment outside this version.
Sharing the repository and reviewed demonstration artifacts does not require
deploying the scanner.

[Back to plan index](README.md)

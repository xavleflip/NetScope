# Part 5: Make installation reproducible

## Goal

Make setup, launch, and verification repeatable for someone cloning the project.

## Tasks

- [ ] Add `requirements.txt` with the supported Streamlit version range.
- [ ] Include any dependencies actually needed by the selected test approach.
- [ ] Review the existing `.gitignore` for environments, secrets, and generated reports.
- [ ] Update the README to match the completed features and report format.
- [ ] Document installation, localhost launch, command-line export, and test commands.
- [ ] Document supported Python versions, security restrictions, and limitations.
- [ ] Verify setup in a fresh virtual environment.

## Completion check

Installation, launch, and tests work from a fresh virtual environment using the
documented instructions. The README describes implemented behavior and clearly
separates future work.

## Verification

Install from `requirements.txt`, run the suite, launch the dashboard on loopback,
and generate a local report. Confirm environment files, secrets, and generated
reports are excluded from source control as intended.

[Back to plan index](README.md) · [Next: Portfolio demonstration](06-portfolio-demonstration.md)

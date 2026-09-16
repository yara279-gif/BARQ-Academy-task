cat > AI_USAGE.md << 'EOF'
# AI usage disclosure

I used AI (Claude) throughout this assessment, mostly as a thinking partner: I pasted
real terminal output and it helped me figure out root causes and what exactly to
change, but I typed every fix myself and ran every command myself for Parts 1 and 2
(log analysis, and all the Docker/NGINX bug fixes in troubleshooting.md).

Closer to the deadline, for validate.py, failure_test.py, backup.sh, restore.sh
and .github/workflows/ci.yml, I asked AI to write the code directly instead of
writing it myself, because I was short on time. I read through what it wrote, ran it
against my real environment, found and fixed one real bug myself (validate.py's
counter check was reading the wrong JSON field), and re-ran everything until it
genuinely passed against my live stack -- not just once, but after environment issues
too (a host restart broke two containers, I fixed that myself and re-ran the tests).
I can explain what each script does and why.

The documentation files (README.md, decisions.md, security_review.md, this file)
were also drafted with AI's help, organizing the real commands, output and commit
history from this assessment into the required format.

Related commits: see troubleshooting.md for Parts 1-2; 3601ad6, b474040,
4884530, d50bcd9 for the scripts and CI; 6ce614b, c51a7ad, 0c8ae5b for the docs.
EOF
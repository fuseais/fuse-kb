# Handling KB files safely

A downloaded knowledge base is a copy of your documents' content. This guide
covers what's in the file, how to decide what belongs in one, how to use
encrypted downloads, and what data leaves your computer when you search.

## What a KB file contains

Anyone who has the file can read all of this:

- **The full text of every passage**, which together is effectively the full
  text of your documents.
- **Document names and page numbers.**
- **Tags Fuse added:** document type, topic area, jurisdiction, and extracted
  names, organizations, dates, and amounts.
- **A numeric index** used for meaning-based search.

A file has no user accounts or permissions. Whoever can open it can read
everything in it.

## Decide what belongs in a downloadable KB

Downloadable KBs suit content that everyone who uses the KB may see.

**Good fits:**

- Employee handbooks and policies
- Benefits guides, plan summaries, and carrier documents
- Payroll procedures, calendars, and tax-form guidance
- Compliance references and internal how-to guides

**Keep out of downloadable KBs:**

- Social Security numbers, tax IDs, and bank or routing numbers
- Individual pay rates, offers, and payroll registers
- Medical, leave, disability, and accommodation records
- Garnishments, background checks, and investigations
- Any file about a specific employee

For employee-level records, use a hosted Fuse knowledge base. Hosted access is
controlled per user, and nothing sits in a file that can be copied. The same
agent tools work with both, so you don't need to rebuild anything to switch.

## Encrypted downloads

Encryption is optional. Standard `.sqlite` downloads are the easiest way to
test, and they're fine for non-sensitive documents. Choose encrypted
downloads when files will be stored or shared outside a tightly controlled
location.

Encrypted downloads use **PGP**, the same encryption most payroll providers,
benefit carriers, and banks use for file exchanges. If your organization
already exchanges PGP-encrypted files with vendors, you can use the same
process and tools.

### How it works

1. You give Fuse your **public key**. Fuse uses it to encrypt each download.
2. Your **private key** stays with you. Only it can decrypt the files, and
   Fuse never has it, so Fuse can't open your downloads either.
3. fuse-kb decrypts the file **in memory** each time it opens it. No readable
   copy is written to disk.

### One-time setup

**If you already have a PGP key** for vendor file exchanges, you can use it,
or create a separate one for knowledge bases so that each can be managed and
rotated on its own.

**To create a key** on the machine that will run your searches:

```bash
gpg --quick-gen-key "Acme HR Knowledge Bases <hr-it@acme.example>" default default 2y
gpg --armor --export hr-it@acme.example > acme-kb-public.asc
```

Upload `acme-kb-public.asc` (the public key) to Fuse. Set a strong passphrase
when prompted, and store it in your password manager. A 2-year expiry is a
sensible default; renew or replace the key before then.

GnuPG comes with most Linux systems. On macOS, run `brew install gnupg`; on
Windows, install [Gpg4win](https://gpg4win.org).

### Opening encrypted files

**On your own computer:** nothing extra. fuse-kb uses your GnuPG keyring, and
GnuPG asks for your passphrase when needed.

```bash
fuse-kb research handbook "dental coverage"     # finds handbook.sqlite.gpg
```

**On a server or in an agent**, keep the private key in your secrets manager
(AWS Secrets Manager, Azure Key Vault, 1Password, and similar) and pass it in
with environment variables:

| Variable | Contains |
|---|---|
| `FUSE_KB_PGP_KEY` | The private key itself (the ASCII-armored text) |
| `FUSE_KB_PGP_KEY_FILE` | Or: a path to the private key file |
| `FUSE_KB_PGP_PASSPHRASE` | The key's passphrase |

fuse-kb loads the key into a temporary keyring held in memory, decrypts, and
deletes the keyring immediately. Don't put the passphrase on the command line,
where it would be saved in shell history; fuse-kb only reads it from the
environment.

### Rotating keys

To replace a key, upload the new public key to Fuse and download fresh copies
of your KBs. Files downloaded earlier still open with the old private key, so
delete those copies before you retire it.

## Storing and sharing files

- **Store KB files only where the documents themselves may be stored.** Use
  an encrypted disk (FileVault, BitLocker, LUKS) on any computer that keeps
  standard `.sqlite` files.
- **Don't email standard files** or upload them to broadly shared drives. If
  a file must travel, use an encrypted download.
- **Never commit KB files to source control.** Add `*.sqlite` and
  `*.sqlite.gpg` to your `.gitignore`.
- **Keep one copy per place it's used**, so there's a short list to update or
  delete.

## Keeping KBs current, and retiring them

A downloaded file is a snapshot. When documents change in Fuse, download the
KB again and replace the old file. When a KB is no longer needed, or a policy
is withdrawn, delete every copy, including those on servers and in agent
deployments. A deleted file can't be recalled from copies made earlier.

## What leaves your computer when you search

Keyword search, metadata filters, and reading pages never send anything
anywhere. Other features send data only to the providers you configure:

| Feature | What is sent | Where |
|---|---|---|
| Meaning-based search, cloud embedder (`bedrock`, `openai`) | Your question | That provider |
| Meaning-based search, local embedder (`ollama`, `sentence-transformers`) | Nothing | Stays on your computer |
| Reranking with `cohere` | Your question and the top 20 passages | AWS Bedrock |
| Reranking with `cross-encoder` | Nothing | Stays on your computer |
| HyDE and `answer`, cloud LLM | Your question and, for answers, the passages used | That LLM provider |
| HyDE and `answer`, `ollama` LLM | Nothing | Stays on your computer |

When you connect a KB to Claude or another AI assistant, the passages the
assistant retrieves become part of that conversation, under that assistant's
data policies. Choose an assistant and plan your organization has approved
for the documents in the KB.

## What fuse-kb does to protect you

- **Opens files read-only.** It never changes a KB file.
- **Never runs code from a file.** A KB can only name one of the built-in
  search models, never custom code.
- **Keeps agents to the KBs you configured.** Agents ask for KBs by name, and
  only the files in your configured folder can be opened.
- **Decrypts in memory.** Encrypted KBs are never written to disk unencrypted.
- **Calls no outside service unless you set one up.**


### Usage
Help:
```bash
python3 deploy.py -h
```
Run (all arguments required):
```bash
python3 deploy.py \
    --release.dir=app/build/outputs/apk/release \
    --app.name=CoolAppp \
    --dropbox.key=$DROPBOX_KEY \
    --dropbox.folder=build \
    --changelog.file=CHANGELOG \
    --template.file=template_file \
    --zapier.hook=$ZAPIER_HOOK \
    --email.to=me@myorg.com,them@myorg.com




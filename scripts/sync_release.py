#!/usr/bin/env python3
"""Sync public release metadata only after verifying the signed feed and archive."""
import argparse,base64,hashlib,json,os,re,subprocess,tempfile,urllib.request,xml.etree.ElementTree as ET
from pathlib import Path
PUBLIC_KEY="NqD4YKWiDIVNSmy871mV3v7wTbMylsp5lM2/MeObH6U="
REPOSITORY="stackof20/stackof20"
SPARKLE="{http://www.andymatuschak.org/xml-namespaces/sparkle}"
def fetch(url):
    headers={"User-Agent":"stackof20-release-sync","Accept":"application/vnd.github+json"} if url.startswith("https://api.github.com/") else {"User-Agent":"stackof20-release-sync"}
    token=os.environ.get("GH_TOKEN")
    if token and url.startswith("https://api.github.com/"):headers["Authorization"]="Bearer "+token
    with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=60) as r:return r.read()
def verify(data,signature):
    sig=base64.b64decode(signature,validate=True)
    if len(sig)!=64:raise ValueError("Invalid signature length")
    key=base64.b64encode(bytes.fromhex("302a300506032b6570032100")+base64.b64decode(PUBLIC_KEY)).decode()
    code="const c=require('node:crypto'),f=require('node:fs');const k=c.createPublicKey({key:Buffer.from(process.argv[2],'base64'),format:'der',type:'spki'});process.exit(c.verify(null,f.readFileSync(process.argv[1]),k,Buffer.from(process.argv[3],'base64'))?0:1)"
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/"payload";p.write_bytes(data)
        subprocess.run(["node","-e",code,str(p),key,signature],check=True,capture_output=True)
def inspect(feed,manifest):
    prefix=b"<!-- sparkle-signatures:\n"
    start=feed.rfind(prefix)
    if start<0:raise ValueError("Unsigned feed")
    end=feed.find(b"-->",start)
    if end<0 or feed[end+3:].strip():raise ValueError("Invalid signature trailer")
    fields=dict(line.split(":",1) for line in feed[start+len(prefix):end].decode().splitlines() if ":" in line)
    if int(fields.get("length","-1").strip())!=start:raise ValueError("Signed length mismatch")
    verify(feed[:start],fields["edSignature"].strip())
    xml=ET.fromstring(feed);items=xml.findall("./channel/item")
    if not items:raise ValueError("Empty feed")
    item=max(items,key=lambda i:int(i.findtext(SPARKLE+"version")))
    version=item.findtext(SPARKLE+"shortVersionString");build=int(item.findtext(SPARKLE+"version"))
    if not re.fullmatch(r"1\.\d+\.\d+",version or "") or build<19:raise ValueError("Unsupported release")
    tag="v"+version+"-"+str(build);expected="https://github.com/"+REPOSITORY+"/releases/download/"+tag+"/stackof20-"+version+"-"+str(build)+".zip"
    enc=item.find("enclosure")
    if enc is None or enc.get("url")!=expected:raise ValueError("Untrusted archive URL")
    if item.findtext(SPARKLE+"hardwareRequirements")!="arm64" or item.findtext(SPARKLE+"minimumSystemVersion")!="15.0.0":raise ValueError("Unexpected platform requirements")
    for key,value in {"version":version,"build":build,"tag":tag,"download_url":expected,"archive_size":int(enc.get("length")),"minimum_macos":"15.0","architecture":"arm64"}.items():
        if manifest.get(key)!=value:raise ValueError("Release metadata mismatch: "+key)
    if not re.fullmatch(r"[a-f0-9]{64}",manifest.get("sha256","")):raise ValueError("Missing checksum")
    return enc
def write(path,data):
    data=data.encode() if isinstance(data,str) else data
    if path.exists() and path.read_bytes()==data:return False
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);return True
def main():
    p=argparse.ArgumentParser();p.add_argument("--target",choices=["site","tap"],required=True);p.add_argument("--root",type=Path,default=Path("."));p.add_argument("--from-dir",type=Path);a=p.parse_args()
    root=a.root.resolve();published_at=None
    if a.from_dir:
        manifest=json.loads((a.from_dir/"release.json").read_text());feed=(a.from_dir/"appcast.xml").read_bytes()
        archive=lambda:(a.from_dir/Path(manifest["download_url"]).name).read_bytes()
    else:
        release=json.loads(fetch("https://api.github.com/repos/"+REPOSITORY+"/releases/latest"))
        if release.get("draft") or release.get("prerelease"):raise ValueError("Only published stable releases")
        assets={v["name"]:v["browser_download_url"] for v in release["assets"]}
        tag=release["tag_name"];prefix="https://github.com/"+REPOSITORY+"/releases/download/"+tag+"/"
        for name in ["release.json","appcast.xml"]:
            if not assets.get(name,"").startswith(prefix):raise ValueError("Missing release asset: "+name)
        manifest=json.loads(fetch(assets["release.json"]));feed=fetch(assets["appcast.xml"]);published_at=release["published_at"]
        if manifest.get("tag")!=tag:raise ValueError("Tag mismatch")
        if assets.get(Path(manifest["download_url"]).name)!=manifest["download_url"]:raise ValueError("Archive asset missing")
        archive=lambda:fetch(manifest["download_url"])
    enc=inspect(feed,manifest)
    old=json.loads((root/"release.json").read_text()) if (root/"release.json").exists() else {}
    if old.get("build",0)>manifest["build"]:raise ValueError("Refusing release rollback")
    if any(old.get(k)!=manifest.get(k) for k in ["sha256","version","build","download_url","archive_size"]):
        data=archive()
        if len(data)!=manifest["archive_size"] or hashlib.sha256(data).hexdigest()!=manifest["sha256"]:raise ValueError("Archive checksum mismatch")
        verify(data,enc.get(SPARKLE+"edSignature"))
    # Store only the documented public schema; no application source or credentials.
    output={k:manifest[k] for k in ["version","build","tag","download_url","archive_size","sha256","minimum_macos","architecture"]}
    output.update(release_url="https://github.com/"+REPOSITORY+"/releases/tag/"+output["tag"],feed_url="https://stackof20.com/updates/v1/appcast.xml",published_at=published_at or manifest.get("published_at"))
    changed=write(root/"release.json",json.dumps(output,indent=2)+"\n")
    if a.target=="site":
        changed=write(root/"updates/v1/appcast.xml",feed) or changed
        for path in root.glob("*.html"):
            s=path.read_text()
            s=re.sub(r'(<a\b[^>]*\bdata-download\b[^>]*\bhref=")[^"]*(")',lambda m:m[1]+output["download_url"]+m[2],s)
            s=re.sub(r'(<span data-release-version>)[^<]*(</span>)',lambda m:m[1]+output["version"]+m[2],s)
            s=re.sub(r'(<span data-release-build>)[^<]*(</span>)',lambda m:m[1]+str(output["build"])+m[2],s)
            s=re.sub(r'(<a\b[^>]*\bdata-release-notes\b[^>]*\bhref=")[^"]*(")',lambda m:m[1]+output["release_url"]+m[2],s)
            changed=write(path,s) or changed
    else:
        text=(root/"scripts/stackof20.rb.in").read_text()
        for k,v in {"VERSION":output["version"],"BUILD":str(output["build"]),"SHA256":output["sha256"],"DOWNLOAD_URL":output["download_url"]}.items():text=text.replace("@"+k+"@",v)
        if re.search(r"@[A-Z_]+@",text):raise ValueError("Unresolved cask field")
        changed=write(root/"Casks/stackof20.rb",text) or changed
    print(("Updated " if changed else "Current ")+a.target+": "+output["tag"])
if __name__=="__main__":main()

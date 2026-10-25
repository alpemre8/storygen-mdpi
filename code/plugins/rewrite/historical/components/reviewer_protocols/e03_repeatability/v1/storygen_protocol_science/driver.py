"""Private API dispatch; only finite owner-selected scientific actions are exposed."""
import argparse,importlib,json,os
from pathlib import Path
from .bindings import WORKSPACE
from binding import fresh_binding,install_owned_server_record,write,sha

def main():
    p=argparse.ArgumentParser();p.add_argument('--module',required=True);p.add_argument('--action',required=True)
    for key in ['protocol-root','parent-config','producer-roots','receipt-dir']:p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--live-server-record',type=Path);p.add_argument('--server-key');p.add_argument('--server-mode')
    a=p.parse_args();root=a.protocol_root
    if a.action=='prepare':
        config=fresh_binding(a.parent_config,root,WORKSPACE,json.loads(a.producer_roots.read_text()))
        result={'scientific_fields_unchanged':True,'config_sha256':sha(root/'CONFIG.json'),'source_commits':config['source_commits']}
    else:
        if a.live_server_record:install_owned_server_record(root,a.server_key,a.live_server_record,mode=a.server_mode)
        module=importlib.import_module('storygen_protocol_science.'+a.module)
        module.execute(a.action,root)
        result={'action':a.action,'protocol_config_sha256':sha(root/'CONFIG.json'),'status':'EXECUTED','scientific_validity':'UNVERIFIED'}
    write(a.receipt_dir/'PROTOCOL_STAGE.json',result)

if __name__=='__main__':main()

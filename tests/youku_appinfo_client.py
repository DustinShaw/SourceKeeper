"""优酷 appinfo 播放 API 完整客户端（探测资产，2026-10-14 实证）

链路（全部沙箱/浏览器双验证）：
1. GET https://www.youku.com/                    -> cookie: csrfToken/isI18n
2. GET https://gm.mmstat.com/yt/vp.vdoview       -> cookie: cna（utid 源）
3. GET https://un-acs.youku.com/h5/mtop...appinfo（sign=seed，无 token）
                                                 -> Set-Cookie: _m_h5_tk
4. GET 播放页 https://v.youku.com/v_show/id_XXX.html
   -> SSR 内联 defaultCkey（base64，静态 ckey 源，UAB 可选增强）
5. GET appinfo（完整参数 + md5 sign + ckey）     -> data.data.stream[].m3u8_url

sign = md5(token + "&" + t + "&" + appKey + "&" + data)
  token = _m_h5_tk cookie 取 "_" 前第一段
  t     = 毫秒时间戳
  data  = URL 编码前的原始 JSON（key 顺序：steal_params 在前）

已知限制：沙箱出口 IP（119.4.178.244）被阿里风控 -> error code -6005「用户账户异常」
（浏览器原声请求同样 -6005，非参数问题；盒子家庭 IP 待验证）
"""
import base64
import gzip
import hashlib
import json
import re
import subprocess
import time
import urllib.parse

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
APP_KEY = '24679788'
API_PATH = 'https://un-acs.youku.com/h5/mtop.youku.play.ups.appinfo.get/1.1/'


def _curl(url, jar, referer, tries=5, timeout=25):
    for _ in range(tries):
        r = subprocess.run(
            ['curl', '-sk', '--max-time', str(timeout), '-b', jar, '-c', jar,
             '-H', 'User-Agent: ' + UA, '-H', 'Referer: ' + referer, url],
            capture_output=True, timeout=timeout + 10)
        if r.returncode == 0 and r.stdout:
            raw = r.stdout
            if raw[:2] == b'\x1f\x8b':
                raw = gzip.decompress(raw)
            return raw.decode('utf-8', 'ignore')
        time.sleep(2)
    return ''


def _curl_headers(url, jar, referer, hdr_out, timeout=25):
    subprocess.run(
        ['curl', '-sk', '--max-time', str(timeout), '-D', hdr_out,
         '-b', jar, '-c', jar, '-H', 'User-Agent: ' + UA,
         '-H', 'Referer: ' + referer, url],
        capture_output=True, timeout=timeout + 10)


def _read_jar(jar):
    ck = {}
    try:
        for line in open(jar, encoding='utf-8'):
            p = line.strip().split('\t')
            if len(p) == 7:
                ck[p[5]] = p[6]
    except OSError:
        pass
    return ck


def seed_session(jar):
    """完整 seed：首页 -> mmstat(cna) -> mtop token"""
    for u in ('https://www.youku.com/', 'https://gm.mmstat.com/yt/vp.vdoview'):
        _curl(u, jar, 'https://www.youku.com/')
        time.sleep(0.8)
    ck = _read_jar(jar)
    if not ck.get('_m_h5_tk'):
        t = str(int(time.time() * 1000))
        url = (API_PATH + '?jsv=2.6.1&appKey=' + APP_KEY + '&t=' + t +
               '&sign=seed&api=mtop.youku.play.ups.appinfo.get&v=1.1'
               '&timeout=15000&type=jsonp&dataType=jsonp&callback=mtopjsonp1&data=' +
               urllib.parse.quote('{"steal_params":"{}","biz_params":"{}"}'))
        _curl_headers(url, jar, 'https://www.youku.com/', jar + '.hdr')
        ck = _read_jar(jar)
        # Set-Cookie 也可能只在响应头
        try:
            hdr = open(jar + '.hdr', encoding='utf-8', errors='ignore').read()
            for m in re.finditer(r'Set-Cookie:\s*([^=]+)=([^;]*)', hdr):
                ck.setdefault(m.group(1).strip(), m.group(2).strip())
        except OSError:
            pass
    return ck


def get_static_ckey(show_url, jar):
    """播放页 SSR 内联 defaultCkey（base64 -> utf8）"""
    html = _curl(show_url, jar, 'https://www.youku.com/')
    m = re.search(r'"defaultCkey":"([^"]+)"', html)
    if not m:
        return None, html
    return base64.b64decode(m.group(1)).decode('utf-8', 'ignore'), html


def build_data(ckey, cna, vid, ts=None):
    """完整 22 字段 biz_params + steal_params（顺序：steal_params 在前）"""
    ts = ts or int(time.time())
    steal = json.dumps({
        'ccode': '0502', 'utid': cna, 'version': '9.22.1',
        'ckey': ckey, 'client_ip': '192.168.1.1', 'client_ts': ts,
    }, separators=(',', ':'), ensure_ascii=False)
    biz = json.dumps({
        'vid': vid, 'h265': 1, 'current_showid': '', 'preferClarity': -1,
        'media_type': 'standard,subtitle', 'app_ver': '9.22.1',
        'extag': 'EXT-X-PRIVINF', 'play_ability': 2164266240,
        'close_ability': 655360, 'master_m3u8': 1, 'drm_type': 3,
        'key_index': 'web01', 'encryptR_client': 'QN2Ahnsha69mwpA8rSotMQ==',
        'local_vid': vid, 'skh': 1, 'last_clarity': -1, 'wdm': 1,
        'pn': 'com.youku.pcweb', 'playMode': 'normal', 'enc_ver': 2,
    }, separators=(',', ':'), ensure_ascii=False)
    ad = json.dumps({
        'vs': '1.0', 'pver': '9.22.1', 'sver': '2.0', 'site': 1, 'aw': 'w',
        'fu': 0, 'd': 0, 'bt': 'pc', 'os': 'win', 'osv': '10', 'dq': 'auto',
        'atm': '', 'partnerid': 'null', 'wintype': 'interior', 'isvert': 0,
        'vip': 0, 'emb': '', 'p': 1, 'rst': 'mp4', 'needbf': 2, 'avs': '1.0',
        'adExtInfo': '{"home_style":"2"}', 'needad': 1,
    }, separators=(',', ':'), ensure_ascii=False)
    return ('{"steal_params":"%s","biz_params":"%s","ad_params":"%s"}'
            % (steal.replace('"', '\\"'), biz.replace('"', '\\"'),
               ad.replace('"', '\\"')))


def get_play_info(jar, ckey, cna, vid, referer='https://www.youku.com/'):
    """请求 appinfo，返回 (ret, data.data)"""
    ck = _read_jar(jar)
    token = ck.get('_m_h5_tk', '').split('_')[0]
    if not token:
        return ['FAIL_SYS_TOKEN_EMPTY'], {}
    t = str(int(time.time() * 1000))
    data = build_data(ckey, cna, vid)
    sign = hashlib.md5(('%s&%s&%s&%s' % (token, t, APP_KEY, data)).encode()).hexdigest()
    url = (API_PATH + '?jsv=2.6.1&appKey=' + APP_KEY + '&t=' + t + '&sign=' + sign +
           '&api=mtop.youku.play.ups.appinfo.get&v=1.1&timeout=15000'
           '&type=jsonp&dataType=jsonp&callback=mtopjsonp1&data=' +
           urllib.parse.quote(data))
    body = _curl(url, jar, referer)
    i = body.find('(')
    if i < 0:
        return ['EMPTY_RESPONSE'], {}
    try:
        resp = json.loads(body[i + 1:body.rfind(')')])
    except ValueError:
        return ['BAD_JSON'], {}
    return resp.get('ret', []), resp.get('data', {}).get('data', {})


if __name__ == '__main__':
    import os
    jar = '/tmp/yk_probe_jar.txt'
    if os.path.exists(jar):
        os.remove(jar)
    ck = seed_session(jar)
    print('cookies:', {k: v[:20] for k, v in ck.items()})
    cna = ck.get('cna', '')
    show_url = 'https://v.youku.com/v_show/id_XNjg0MzI1MTk2MA==.html'
    ckey, html = get_static_ckey(show_url, jar)
    print('static ckey:', (ckey or '')[:30], 'len', len(ckey or ''))
    ret, data = get_play_info(jar, '140#' + (ckey or ''), cna, 'XNjg0MzI1MTk2MA==', show_url)
    print('ret:', ret)
    err = data.get('error')
    if err:
        print('error:', err)
    streams = data.get('stream') or []
    print('streams:', len(streams))
    for s in streams[:5]:
        print('  %s %sx%s m3u8=%s' % (s.get('stream_type'), s.get('width'),
                                      s.get('height'), str(s.get('m3u8_url'))[:90]))

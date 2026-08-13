/**
 * Cloudflare Worker — 微信客服(kf)回调 → DeepSeek 提取 DDL → 飞书多维表格
 *
 * 部署到 Cloudflare Workers，把 URL 填到「微信客服 → 接入配置 → 回调配置」。
 *
 * 微信客服消息流程（与公众号不同）：
 *   1. GET  验证URL：msg_signature=sha1(sort(token,timestamp,nonce,echostr)) → 解密 echostr → 返回明文
 *   2. POST 收到加密事件：解密得到 kf_msg_or_event（只含 Token + OpenKfId，不含消息正文）
 *   3. 调用 sync_msg 拉取消息正文
 *   4. 提取 DDL → 写入多维表格 → 调用 send_msg 回复
 *
 * 需要的环境变量（Cloudflare Worker → Settings → Variables）：
 *   WECHAT_TOKEN        回调 Token
 *   WECHAT_AES_KEY      回调 EncodingAESKey（43 位）
 *   WECHAT_CORP_ID      企业ID（corpid，以 ww 开头，在企业微信管理后台「我的企业」里看）
 *   WECHAT_KF_SECRET    可调用接口的自建应用的 Secret（用于 gettoken）
 *   DEEPSEEK_KEY        DeepSeek API key
 *   FEISHU_APP_ID / FEISHU_APP_SECRET   飞书自建应用凭据
 *   BITABLE_APP_TOKEN   多维表格的 app_token（或用 FEISHU_WIKI_TOKEN 自动解析）
 *   FEISHU_WIKI_TOKEN   多维表格所在的 wiki 节点 token（可选，配合 FEISHU_TABLE_ID）
 *   FEISHU_TABLE_ID     多维表格数据表 table_id
 *   DDL_KV              可选：绑定一个 KV namespace 用于消息去重（避免重复提取）
 */

// ── WeChat 消息加解密 (WXBizMsgCrypt) ──────────────────────────────

function decodeAESKey(key) {
  // EncodingAESKey 是 43 位 base64，补 = 才能解码
  const padded = key + '='.repeat((4 - key.length % 4) % 4);
  return Uint8Array.from(atob(padded), c => c.charCodeAt(0));
}

function base64ToBytes(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

async function decryptMsg(encrypted, encodingAESKey, receiveId) {
  const key = decodeAESKey(encodingAESKey);
  const cipher = await crypto.subtle.importKey('raw', key, { name: 'AES-CBC' }, false, ['decrypt']);
  const iv = key.slice(0, 16);
  const ct = base64ToBytes(encrypted);
  const buf = await crypto.subtle.decrypt({ name: 'AES-CBC', iv }, cipher, ct);
  const raw = new Uint8Array(buf);

  // 去掉 PKCS#7 填充
  const padLen = raw[raw.length - 1];
  const content = raw.slice(0, raw.length - padLen);

  // 结构：random(16) + msgLen(4字节大端) + msg + receiveId
  const msgLen = ((content[16] << 24) | (content[17] << 16) | (content[18] << 8) | content[19]) >>> 0;
  const msgBytes = content.slice(20, 20 + msgLen);
  const msg = new TextDecoder('utf-8').decode(msgBytes);

  const ridBytes = content.slice(20 + msgLen);
  const ridStr = new TextDecoder('utf-8').decode(ridBytes);
  if (receiveId && ridStr !== receiveId) {
    // 只告警不抛错：receiveId 配错时验证也能先通过，方便定位真正的 receiveId
    console.warn(`[DECRYPT] receiveId mismatch: expected=${receiveId} got=${ridStr}`);
  }
  return msg;
}

async function sha1(data) {
  const h = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(data));
  return Array.from(new Uint8Array(h)).map(b => b.toString(16).padStart(2, '0')).join('');
}

async function genSignature(token, timestamp, nonce, encrypted) {
  const items = [token, timestamp, nonce, encrypted].sort();
  return await sha1(items.join(''));
}

// ── XML 取值 ────────────────────────────────────────────────────────

function xmlVal(xml, tag) {
  const m = xml.match(new RegExp(`<${tag}><!\\[CDATA\\[(.*?)\\]\\]></${tag}>`));
  return m ? m[1] : '';
}

// ── 企业微信 API（微信客服） ────────────────────────────────────────

async function getAccessToken(corpId, secret) {
  const r = await fetch(
    `https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid=${corpId}&corpsecret=${secret}`
  );
  const d = await r.json();
  if (d.errcode !== 0) throw new Error(`gettoken fail: ${d.errcode} ${d.errmsg}`);
  return d.access_token;
}

// 拉取客服消息（分页）
async function syncMsg(accessToken, token, openKfId, cursor) {
  const r = await fetch(
    `https://qyapi.weixin.qq.com/cgi-bin/kf/sync_msg?access_token=${accessToken}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cursor, token, limit: 1000, open_kfid: openKfId }),
    }
  );
  const d = await r.json();
  if (d.errcode !== 0) throw new Error(`sync_msg fail: ${d.errcode} ${d.errmsg}`);
  return d;
}

// 回复客服消息
async function sendMsg(accessToken, touser, openKfId, content) {
  const r = await fetch(
    `https://qyapi.weixin.qq.com/cgi-bin/kf/send_msg?access_token=${accessToken}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ touser, open_kfid: openKfId, msgtype: 'text', text: { content } }),
    }
  );
  return await r.json();
}

// ── 飞书多维表格 ────────────────────────────────────────────────────

async function getFeishuToken(appId, appSecret) {
  const r = await fetch('https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ app_id: appId, app_secret: appSecret }),
  });
  const d = await r.json();
  if (d.code !== 0) throw new Error(`feishu token fail: ${d.msg}`);
  return d.tenant_access_token;
}

async function resolveBitableToken(fsToken, wikiToken) {
  const r = await fetch(
    `https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node?token=${wikiToken}`,
    { headers: { Authorization: `Bearer ${fsToken}` } }
  );
  const d = await r.json();
  if (d.code !== 0) throw new Error(`resolve wiki fail: ${d.msg}`);
  return d.data.node.obj_token;
}

async function addBitableRecord(fsToken, appToken, tableId, fields) {
  const r = await fetch(
    `https://open.feishu.cn/open-apis/bitable/v1/apps/${appToken}/tables/${tableId}/records`,
    {
      method: 'POST',
      headers: { Authorization: `Bearer ${fsToken}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ records: [{ fields }] }),
    }
  );
  return await r.json();
}

// ── DeepSeek 提取 ───────────────────────────────────────────────────

async function extractDDL(text, apiKey) {
  const prompt = `你是一个信息提取助手。从以下消息中提取DDL（截止日期）信息，以JSON格式输出：
{
  "标题": "消息核心主题，10-20字",
  "描述": "消息详细摘要",
  "截止日期": "格式 yyyy-MM-dd HH:mm:ss，没有则留空",
  "状态": "固定填'待办'"
}
规则：
1. 截止日期只提取明确时间，如"8月20日前""下周五前"
2. 标题精炼概括，不超过20字
3. 只输出JSON，不要其他文字

消息：${text}`;

  const r = await fetch('https://api.deepseek.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: 'deepseek-chat',
      messages: [{ role: 'user', content: prompt }],
      temperature: 0.1,
    }),
  });
  const d = await r.json();
  const content = d.choices?.[0]?.message?.content || '';
  try {
    const json = content.replace(/```json\n?/g, '').replace(/```/g, '').trim();
    return JSON.parse(json);
  } catch {
    return { 标题: '解析失败', 描述: content, 截止日期: null, 状态: '待办' };
  }
}

// 把 "yyyy-MM-dd HH:mm:ss" 之类的字符串转成毫秒时间戳（多维表格日期列需要）
function parseDeadlineMs(s) {
  if (!s) return null;
  let str = String(s).trim().replace(/[年月]/g, '-').replace(/日/g, '').replace(/\//g, '-');
  const m = str.match(/(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?/);
  if (!m) return null;
  const dt = new Date(+m[1], +m[2] - 1, +m[3], m[4] ? +m[4] : 0, m[5] ? +m[5] : 0, m[6] ? +m[6] : 0);
  return isNaN(dt.getTime()) ? null : dt.getTime();
}

// ── 消息去重（KV 可选） ─────────────────────────────────────────────

async function getLastSyncTime(kv, openKfId) {
  if (!kv) return 0;
  const v = await kv.get(`last_sync:${openKfId}`);
  return v ? parseInt(v, 10) : 0;
}

async function setLastSyncTime(kv, openKfId, t) {
  if (!kv) return;
  await kv.put(`last_sync:${openKfId}`, String(t));
}

// ── 处理 kf_msg_or_event ────────────────────────────────────────────

async function handleKfEvent(token, openKfId, env) {
  const accessToken = await getAccessToken(env.WECHAT_CORP_ID, env.WECHAT_KF_SECRET);
  const lastSyncTime = await getLastSyncTime(env.DDL_KV, openKfId);

  // 飞书 token（一次拉取）
  const fsToken = await getFeishuToken(env.FEISHU_APP_ID, env.FEISHU_APP_SECRET);
  let appToken = env.BITABLE_APP_TOKEN;
  if (!appToken && env.FEISHU_WIKI_TOKEN) {
    appToken = await resolveBitableToken(fsToken, env.FEISHU_WIKI_TOKEN);
  }
  if (!appToken) throw new Error('缺少 BITABLE_APP_TOKEN 或 FEISHU_WIKI_TOKEN');

  let cursor = '';
  let maxSendTime = lastSyncTime;
  let saved = 0;

  // 分页拉取
  do {
    const data = await syncMsg(accessToken, token, openKfId, cursor);
    const msgList = data.msg_list || [];

    for (const msg of msgList) {
      const sendTime = msg.send_time || 0;
      if (sendTime > maxSendTime) maxSendTime = sendTime;

      // 只看客户发来的文本消息（origin: 3=客户 4=系统 5=接待人员）
      if (msg.origin !== 3) continue;
      if (msg.msgtype !== 'text') {
        // 非文本：提示一下
        await sendMsg(accessToken, msg.external_userid, openKfId, '请直接发送或转发文字消息，我会帮你提取 DDL 信息。');
        continue;
      }

      const text = (msg.text && msg.text.content) || '';
      if (!text || sendTime <= lastSyncTime) continue;

      let extracted;
      try {
        extracted = await extractDDL(text, env.DEEPSEEK_KEY);
      } catch (e) {
        await sendMsg(accessToken, msg.external_userid, openKfId, '提取 DDL 时出错，请稍后重试。');
        continue;
      }

      const deadlineMs = parseDeadlineMs(extracted.截止日期);
      await addBitableRecord(fsToken, appToken, env.FEISHU_TABLE_ID, {
        '标题': extracted.标题 || '',
        '描述': extracted.描述 || '',
        '截止日期': deadlineMs,           // 毫秒时间戳，null 表示无
        '原始文本': text.slice(0, 5000),
        '来源': '📱 微信',
        '添加日期': Date.now(),
        '状态': '待办',
      });
      saved++;

      let reply = `✅ 已保存：${extracted.标题}`;
      if (deadlineMs) reply += `\n📅 截止：${extracted.截止日期}`;
      else reply += '\n（未识别到明确的截止日期）';
      await sendMsg(accessToken, msg.external_userid, openKfId, reply);
    }

    cursor = data.next_cursor || '';
  } while (data_has_more(data));

  await setLastSyncTime(env.DDL_KV, openKfId, maxSendTime);
  return saved;
}

function data_has_more(data) {
  return data.has_more === 1;
}

// ── 主入口 ──────────────────────────────────────────────────────────

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const params = url.searchParams;

    // 打日志：看每个请求的方法/路径/参数（方便排查验证请求有没有打进来）
    console.log(`[REQ] ${request.method} ${url.pathname} sig=${params.get('msg_signature') || params.get('signature') || ''} echo=${params.get('echostr') ? 'YES' : 'no'} ts=${params.get('timestamp') || ''} nonce=${params.get('nonce') || ''}`);

    // ── GET：验证 URL ──
    // 两套机制都支持：企业微信/微信客服用 msg_signature+解密；公众号用 signature+原样返回
    if (request.method === 'GET' && params.get('echostr')) {
      const ts = params.get('timestamp') || '';
      const nonce = params.get('nonce') || '';
      const echostr = params.get('echostr') || '';

      const msgSig = params.get('msg_signature') || '';
      const sig = params.get('signature') || '';

      // 方案一：企业微信/微信客服 —— msg_signature = sha1(sort(token,ts,nonce,echostr))，解密 echostr
      if (msgSig) {
        const expectedSig = await genSignature(env.WECHAT_TOKEN, ts, nonce, echostr);
        console.log(`[VERIFY-wecom] msgSig=${msgSig} expected=${expectedSig} match=${msgSig === expectedSig}`);
        if (msgSig !== expectedSig) {
          return new Response('signature fail', { status: 403 });
        }
        try {
          const decrypted = await decryptMsg(echostr, env.WECHAT_AES_KEY, env.WECHAT_CORP_ID);
          return new Response(decrypted, {
            headers: { 'Content-Type': 'text/plain; charset=utf-8' },
          });
        } catch (e) {
          return new Response(`decrypt fail: ${e.message}`, { status: 500 });
        }
      }

      // 方案二：公众号 —— signature = sha1(sort(token,ts,nonce))，直接返回 echostr
      if (sig) {
        const items = [env.WECHAT_TOKEN, ts, nonce].sort();
        const expectedSig = await sha1(items.join(''));
        console.log(`[VERIFY-mp] sig=${sig} expected=${expectedSig} match=${sig === expectedSig}`);
        if (sig !== expectedSig) {
          return new Response('signature fail', { status: 403 });
        }
        return new Response(echostr, {
          headers: { 'Content-Type': 'text/plain; charset=utf-8' },
        });
      }

      // 没有签名参数：异常情况
      console.log('[VERIFY] no msg_signature/signature in GET');
      return new Response('no signature', { status: 400 });
    }

    // ── POST：接收加密事件回调 ──
    if (request.method === 'POST' && params.get('msg_signature')) {
      const body = await request.text();
      const msgSig = params.get('msg_signature') || '';
      const ts = params.get('timestamp') || '';
      const nonce = params.get('nonce') || '';

      const encMatch = body.match(/<Encrypt><!\[CDATA\[(.*?)\]\]><\/Encrypt>/);
      if (!encMatch) {
        // 没有 Encrypt：仍按微信要求返回 success
        return new Response('success', { status: 200 });
      }
      const encrypted = encMatch[1];

      const expectedSig = await genSignature(env.WECHAT_TOKEN, ts, nonce, encrypted);
      if (msgSig !== expectedSig) {
        return new Response('signature fail', { status: 403 });
      }

      let decrypted;
      try {
        decrypted = await decryptMsg(encrypted, env.WECHAT_AES_KEY, env.WECHAT_CORP_ID);
      } catch (e) {
        // 解密失败也要回 success，否则微信会反复重试
        return new Response('success', { status: 200 });
      }

      const msgType = xmlVal(decrypted, 'MsgType');
      const event = xmlVal(decrypted, 'Event');

      // 只处理 kf_msg_or_event
      if (msgType === 'event' && event === 'kf_msg_or_event') {
        const token = xmlVal(decrypted, 'Token');
        const openKfId = xmlVal(decrypted, 'OpenKfId');
        if (token && openKfId) {
          await handleKfEvent(token, openKfId, env).catch(e => {
            console.error('handleKfEvent error:', e && e.message);
          });
        }
      }

      // 微信要求回 "success"，否则会重试
      return new Response('success', { status: 200 });
    }

    return new Response('dontmissddl worker', { status: 200 });
  },
};

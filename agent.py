import json
import os
import re
import httpx
from openai import AsyncOpenAI
from datetime import datetime
from storage import load_config, load_rules, load_conversation, save_conversation

# Only fields with these words are shown as stat cards
_STAT_ALLOW_WORDS = {
    'total', 'count', 'present', 'absent', 'leave', 'days',
    'holiday', 'working', 'elapsed', 'pending', 'approved',
}

# Lists with these words in their key are skipped for the main table
_LIST_SKIP_WORDS = {'geofence', 'route', 'area', 'config', 'setting', 'image', 'meta', 'log', 'audit', 'credential', 'profile_image'}

# Lists with these words are preferred as the main staff/subordinate table
_LIST_PREFER_WORDS = {'staff', 'subordinate', 'employee', 'member', 'user', 'person', 'children', 'report', 'team', 'contour'}


def _short_title(description: str) -> str:
    """Take first sentence or first 40 chars of description."""
    idx = description.find('.')
    if 0 < idx <= 50:
        return description[:idx]
    return description[:42].rstrip() + ('…' if len(description) > 42 else '')


def _is_stat_key(k: str, v) -> bool:
    """Only allow attendance/count fields as stats — nothing else."""
    if isinstance(v, bool):
        return False
    if not isinstance(v, (int, float)):
        return False
    kl = k.lower()
    return any(w in kl for w in _STAT_ALLOW_WORDS)


def _best_list(data: dict) -> tuple[str, list] | None:
    """Find the most relevant list in the response to show as a table."""
    if not isinstance(data, dict):
        return None
    candidates = []
    for k, v in data.items():
        if not (isinstance(v, list) and v and isinstance(v[0], dict)):
            continue
        kl = k.lower()
        if any(w in kl for w in _LIST_SKIP_WORDS):
            score = -1
        elif any(w in kl for w in _LIST_PREFER_WORDS):
            score = 2
        else:
            # Prefer lists whose items have a 'name' field (likely people)
            score = 1 if 'name' in {ck.lower() for ck in v[0].keys()} else 0
        candidates.append((score, k, v))
    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[0])
    best = candidates[0]
    if best[0] < 0:
        return None
    return best[1], best[2]


def _fmt_label(k: str) -> str:
    return k.replace('total_', '').replace('_', ' ').title()


# Advanced mapping covering colloquial expressions, abbreviations, and system flags
_SIMPLE_FIELD_MAP = {
    'name':               ['name', 'staff_name', 'full_name', 'employee_name'],
    'phone':              ['phone', 'mobile', 'contact', 'phone_number', 'mobile_no'],
    'email':              ['email', 'email_id', 'email_address', 'mail'],
    'designation':        ['designation', 'title', 'job_title', 'position'],
    'department':         ['department', 'dept', 'division'],
    'role':               ['role', 'role_name', 'role_type'],
    'supervisor':         ['supervisor', 'reporting_to', 'manager', 'relative_name', 'staff_id', 'relativeName'],
    'gender':             ['gender', 'sex'],
    'dob':                ['dob', 'date_of_birth', 'birth_date', 'birthdate'],
    'id':                 ['id', 'staff_id', 'employee_id', 'emp_id'],
    'employee id':        ['employee_id', 'emp_id', 'employeeid', 'employeeId'],
    'profile image':      ['avatar', 'profile_image', 'photo', 'image_url', 'picture'],
    'profile picture':    ['avatar', 'profile_image', 'photo', 'image_url', 'picture'],
    'photo':              ['avatar', 'profile_image', 'photo', 'image_url', 'picture'],
    'avatar':             ['avatar', 'profile_image', 'photo', 'image_url'],
    'image':              ['avatar', 'profile_image', 'photo', 'image_url', 'picture'],
    'picture':            ['avatar', 'profile_image', 'photo', 'image_url', 'picture'],
    'is supervisor':      ['isSupervisor', 'is_supervisor', 'has_subordinates'],
    'admin access':       ['hasAdminAccess', 'admin_access', 'is_admin'],
    'geofence enabled':   ['geofenceEnable', 'is_geofence_enabled'],
    'strict geofence':    ['isStrictGeofenceEnabled', 'strict_geofence'],
    'strict shift':       ['isStrictShiftEnabled', 'strict_shift'],
    'cross day checkout': ['allowCrossDayCheckout', 'cross_day'],
    'holiday attendance': ['allowAttendanceOnHoliday', 'holiday_attendance'],
    'tracking distance':  ['trackingDistanceThreshold', 'distance_threshold'],
    'staff type':         ['staffTypeInfo', 'staff_type', 'type_info'],
}

# Fields whose values are image URLs — show as <img> instead of plain text
_IMAGE_FIELDS = {'avatar', 'profile_image', 'photo', 'image_url', 'picture'}


def _format_shift_html(shifts: list) -> str:
    """Format shiftDetails array as a readable HTML card."""
    if not shifts:
        return '<p style="color:#aaa;font-size:13px">No shift information available.</p>'
    rows = ''
    for i, s in enumerate(shifts):
        name = s.get('name') or s.get('shift_name') or f'Shift {i+1}'
        start = s.get('start_time') or s.get('start') or ''
        end = s.get('end_time') or s.get('end') or ''
        days = s.get('days') or s.get('working_days') or ''
        restriction = s.get('restriction') or s.get('restrictions') or ''
        rows += f'''
        <div style="background:#0f3460;border-radius:10px;padding:12px;margin-bottom:8px">
          <div style="color:#00C9A7;font-size:13px;font-weight:bold;margin-bottom:6px">{name}</div>
          <div style="display:flex;gap:12px;flex-wrap:wrap;font-size:11px;color:#ccc">
            <span>🕐 {start} – {end}</span>
            {f'<span>📅 {days}</span>' if days else ''}
          </div>
          {f'<div style="color:#f0a500;font-size:10px;margin-top:4px">⚠ {restriction}</div>' if restriction else ''}
        </div>'''
    return f'''
    <div style="background:#16213e;border-radius:12px;padding:12px">
      <div style="color:#00C9A7;font-size:12px;font-weight:bold;margin-bottom:8px">Work Shifts</div>
      {rows}
    </div>'''


def _format_shift_text(shifts: list) -> str:
    """Format shiftDetails as plain text."""
    if not shifts:
        return "No shift information available."
    lines = []
    for i, s in enumerate(shifts):
        name = s.get('name') or s.get('shift_name') or f'Shift {i+1}'
        start = s.get('start_time') or s.get('start') or ''
        end = s.get('end_time') or s.get('end') or ''
        days = s.get('days') or s.get('working_days') or ''
        line = f"• {name}: {start} – {end}"
        if days:
            line += f" ({days})"
        lines.append(line)
    return '\n'.join(lines)


_HINDI_TRIGGERS = ('mera', 'meri', 'kaun hoon', 'main kaun', 'kya he', 'kya hai',
                   'bata', 'batao', 'dikha', 'dikhao', 'mere')

def _is_hindi(q: str) -> bool:
    return any(t in q for t in _HINDI_TRIGGERS)


def _get_recursive_subordinates(sub_list: list) -> list:
    """Recursively traverse through team hierarchies to find all subordinates."""
    all_subs = []
    for sub in sub_list:
        if isinstance(sub, dict):
            all_subs.append(sub)
            nested = sub.get('subordinates', [])
            if isinstance(nested, list) and nested:
                all_subs.extend(_get_recursive_subordinates(nested))
    return all_subs


def _try_simple_answer(question: str, result) -> str | None:
    """If user asked for one specific field or boolean flag, return a plain-text/card answer."""
    q = question.lower()

    # Broad detection of conversational inquiry keywords
    simple_triggers = ('what is my', 'what\'s my', 'my name', 'my phone',
                       'my email', 'my designation', 'my department', 'my role',
                       'my gender', 'my dob', 'my id', 'my employee', 'my supervisor',
                       'my shift', 'my schedule', 'my areas', 'my area',
                       'who am i', 'tell me my', 'show my name', 'whats my',
                       'my profile image', 'my profile picture', 'my photo',
                       'my avatar', 'my image', 'my picture',
                       'profile image', 'profile photo', 'profile picture',
                       'show me', 'show my', 'am i a', 'can i', 'do i have',
                       'is my', 'who is under me', 'my subordinates', 'my team',
                       'how many subordinates', 'who reports to me',
                       # Hindi triggers
                       'mera name', 'mera naam', 'meri email', 'mera phone',
                       'mera id', 'mera department', 'mera designation', 'mera role',
                       'mera supervisor', 'mera shift', 'kaun hoon', 'main kaun',
                       'mere subordinates', 'mera team', 'mere niche kaun')
    if not any(t in q for t in simple_triggers):
        return None

    # Unwrap the data to find a flat dict
    data = result
    if isinstance(result, list) and result:
        data = result[0] if isinstance(result[0], dict) else {}
    elif isinstance(result, dict):
        for key in ('data', 'result', 'response'):
            val = result.get(key)
            if isinstance(val, list) and val:
                data = val[0] if isinstance(val[0], dict) else {}
                break
            elif isinstance(val, dict):
                data = val
                break

    if not isinstance(data, dict):
        return None

    # 1. Handle shift queries
    if 'shift' in q or 'schedule' in q:
        shifts = data.get('shiftDetails') or data.get('shift_details') or data.get('shifts')
        if isinstance(shifts, list) and shifts:
            return _format_shift_html(shifts)

    # 2. Handle geographic assigned areas
    if 'area' in q or 'zone' in q:
        areas = data.get('areas') or data.get('assigned_areas')
        if isinstance(areas, list) and areas:
            names = [a.get('name', '?') for a in areas if isinstance(a, dict)]
            if _is_hindi(q):
                return f"आपके आवंटित क्षेत्र (Areas) हैं: {', '.join(names)}"
            return f"Your assigned areas are: {', '.join(names)}."

    # 3. Handle subordinate / hierarchical tree queries recursively
    if 'subordinate' in q or 'team' in q or 'report' in q or 'under me' in q or 'niche' in q:
        subs = data.get('subordinates')
        if isinstance(subs, list):
            all_subs = _get_recursive_subordinates(subs)
            if not all_subs:
                return "You currently have no subordinates reporting to you." if not _is_hindi(q) else "आपके नीचे कोई subordinate नहीं है।"
            names = [s.get('name', '?') for s in all_subs if isinstance(s, dict)]
            if _is_hindi(q):
                return f"आपके कुल {len(names)} subordinates हैं: {', '.join(names[:15])}"
            return f"You have {len(names)} total subordinates in your reporting hierarchy: {', '.join(names[:15])}"

    # 4. Handle Boolean and configuration permission questions
    bool_queries = {
        'admin': ('hasAdminAccess', "You have Admin Access.", "You do not have Admin Access."),
        'geofence': ('geofenceEnable', "Geofence tracking is enabled for you.", "Geofence is disabled for you."),
        'strict geofence': ('isStrictGeofenceEnabled', "Strict geofencing is enabled.", "Strict geofencing is disabled."),
        'holiday': ('allowAttendanceOnHoliday', "You are allowed to mark attendance on holidays.", "Attendance on holidays is not allowed for you."),
        'supervisor': ('isSupervisor', "Yes, you are marked as a Supervisor.", "No, you are not marked as a Supervisor."),
        'cross day': ('allowCrossDayCheckout', "Cross-day checkout is allowed.", "Cross-day checkout is not allowed.")
    }
    for key_phrase, (field_key, pos_msg, neg_msg) in bool_queries.items():
        if key_phrase in q and field_key in data:
            val = data.get(field_key)
            if _is_hindi(q):
                pos_msg_hi = f"हाँ, {key_phrase} सक्रिय (enabled) है।"
                neg_msg_hi = f"नहीं, {key_phrase} निष्क्रिय (disabled) है।"
                return pos_msg_hi if val else neg_msg_hi
            return pos_msg if val else neg_msg

    # 5. Try to find standard fields via the comprehensive map
    for keyword, fields in _SIMPLE_FIELD_MAP.items():
        if keyword in q:
            for field in fields:
                value = (data.get(field) or data.get(field.title()) or
                         data.get(''.join(w.capitalize() for w in field.split('_'))))
                if value is not None and not isinstance(value, (list, bool)):
                    # Extract nested dict text like staffTypeInfo: {"name": "Nigam"}
                    if isinstance(value, dict):
                        value = value.get('name') or str(value)
                    # For image fields, return a styled profile picture card
                    if field in _IMAGE_FIELDS and str(value).startswith('http'):
                        return (
                            f'<html><body style="background:#1a1a2e;margin:0;padding:16px;'
                            f'display:flex;flex-direction:column;align-items:center;font-family:sans-serif">'
                            f'<p style="color:#aaa;font-size:12px;margin-bottom:12px">Your profile photo</p>'
                            f'<img src="{value}" style="width:120px;height:120px;border-radius:60px;'
                            f'object-fit:cover;border:3px solid #00C9A7">'
                            f'</body></html>'
                        )
                    if _is_hindi(q):
                        return f"आपका {keyword} है: {value}"
                    return f"Your {keyword} is {value}."

    # 6. Fallback: If question explicitly asks for "name", try generic name keys
    if 'name' in q or 'naam' in q:
        for field in ['name', 'staff_name', 'full_name']:
            if data.get(field):
                if _is_hindi(q):
                    return f"आपका नाम है: {data[field]}"
                return f"Your name is {data[field]}."

    return None  # Can't answer simply — fall back to generating HTML summary card


def _format_result_html(description: str, result: dict, user_id: str, now: datetime) -> str:
    """Format API result as mobile-optimized HTML — no second LLM call needed."""
    if isinstance(result, dict) and result.get('error'):
        return (
            '<html><body style="background:#1a1a2e;color:#ff6b6b;font-family:sans-serif;padding:16px;margin:0">'
            f'<p style="font-size:14px">⚠️ {result["error"]}</p></body></html>'
        )

    top_list = None
    if isinstance(result, list) and result:
        top_list = result
        data = result[0] if isinstance(result[0], dict) else {}
    else:
        data = result
        if isinstance(result, dict):
            for key in ('data', 'result', 'response'):
                val = result.get(key)
                if isinstance(val, dict):
                    data = val
                    break
                elif isinstance(val, list) and val:
                    top_list = val
                    data = val[0] if isinstance(val[0], dict) else {}
                    break

    name_for_title = (data.get('staff_name') or data.get('name') or '') if isinstance(data, dict) else ''
    month_for_title = (data.get('month_name') or '') if isinstance(data, dict) else ''
    if month_for_title:
        year_for_title = (data.get('year') or now.year) if isinstance(data, dict) else now.year
        title = f"{month_for_title} {year_for_title}"
    elif name_for_title:
        title = name_for_title
    elif top_list is not None:
        title = "Staff List"
    else:
        title = "Details"

    # -- Stat cards --
    stats = {k: v for k, v in (data.items() if isinstance(data, dict) else {}.items())
             if _is_stat_key(k, v)}

    best = None
    if top_list is not None:
        best = ('items', top_list)
        if not stats:
            stats['__list__items'] = (len(top_list), 'Total Staff')
    else:
        best = _best_list(data) if isinstance(data, dict) else None
        if best and not stats:
            list_key, list_val = best
            stats[f'__list__{list_key}'] = (len(list_val), list_key.replace('_', ' ').title())

    stat_cards = ''
    for k, v in list(stats.items())[:4]:
        if k.startswith('__list__'):
            count, label = v
            stat_cards += (
                f'<div style="flex:1;min-width:calc(50% - 6px);background:#0f3460;border-radius:10px;'
                f'padding:12px 8px;text-align:center;box-sizing:border-box">'
                f'<div style="font-size:28px;font-weight:bold;color:#00C9A7">{count}</div>'
                f'<div style="font-size:11px;color:#aaa;margin-top:3px">{label}</div></div>'
            )
        else:
            color = '#ff6b6b' if 'absent' in k.lower() else '#f0a500' if 'leav' in k.lower() else '#00C9A7'
            display = int(v) if isinstance(v, float) and v == int(v) else v
            stat_cards += (
                f'<div style="flex:1;min-width:calc(50% - 6px);background:#0f3460;border-radius:10px;'
                f'padding:12px 8px;text-align:center;box-sizing:border-box">'
                f'<div style="font-size:28px;font-weight:bold;color:{color}">{display}</div>'
                f'<div style="font-size:11px;color:#aaa;margin-top:3px">{_fmt_label(k)}</div></div>'
            )

    # -- Subtitle --
    name = (data.get('staff_name') or data.get('name') or '') if isinstance(data, dict) else ''
    month_name = (data.get('month_name') or '') if isinstance(data, dict) else ''
    subtitle_parts = []
    if month_name:
        year = (data.get('year') or now.year) if isinstance(data, dict) else now.year
        subtitle_parts.append(f'{month_name} {year}')
    if name:
        subtitle_parts.append(name)
    if user_id:
        subtitle_parts.append(f'Staff ID: {user_id}')
    subtitle = ' • '.join(subtitle_parts)

    # -- Donut chart for attendance --
    present  = int(data.get('total_present', 0))  if isinstance(data, dict) else 0
    absent   = int(data.get('total_absent', 0))   if isinstance(data, dict) else 0
    holidays = int(data.get('total_holidays', 0)) if isinstance(data, dict) else 0
    leaves   = int(data.get('total_leaves', 0))   if isinstance(data, dict) else 0
    chart_section = ''
    if present + absent + holidays + leaves > 0:
        chart_section = f"""
  <div style="background:#16213e;border-radius:12px;padding:12px;margin-top:8px">
    <div style="color:#00C9A7;font-size:12px;font-weight:bold;margin-bottom:8px">Attendance Distribution</div>
    <div style="width:140px;height:140px;margin:0 auto"><canvas id="ch"></canvas></div>
    <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;justify-content:center;font-size:10px;color:#ccc">
      <span>🟢 Present: {present}</span><span>🔴 Absent: {absent}</span>
      <span>🟡 Holiday: {holidays}</span><span>🔵 Leave: {leaves}</span>
    </div>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
  <script>
    new Chart(document.getElementById('ch'),{{
      type:'doughnut',
      data:{{labels:['Present','Absent','Holiday','Leave'],
             datasets:[{{data:[{present},{absent},{holidays},{leaves}],
             backgroundColor:['#00C9A7','#ff6b6b','#f0a500','#7c83fd'],borderWidth:0}}]}},
      options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}}}}
    }});
  </script>"""

    # -- Details table (smart: prefer staff/subordinate lists) --
    table_section = ''
    found = best
    if found:
        list_key, list_val = found
        _skip_cols = {'token', 'secret', 'password', 'fcm', 'firebase', 'device_token', 'profile_image_meta_data', 'credentialInfo'}
        all_cols = list(list_val[0].keys())
        priority = ['name', 'staff_name', 'id', 'staff_id', 'status', 'date', 'phone']
        cols = [c for c in priority if c in all_cols]
        cols += [c for c in all_cols if c not in cols and not any(w in c.lower() for w in _skip_cols)]
        cols = cols[:4]
        th = ''.join(
            f'<th style="padding:6px 4px;color:#00C9A7;font-size:11px;text-align:left;'
            f'border-bottom:1px solid #333;white-space:nowrap">{c.replace("_"," ").title()}</th>'
            for c in cols
        )
        rows = ''
        for row in list_val[:30]:
            cells = ''.join(
                f'<td style="padding:6px 4px;border-bottom:1px solid #1e2a4a;color:#ccc;font-size:11px">'
                f'{row.get(c, "")}</td>'
                for c in cols
            )
            rows += f'<tr>{cells}</tr>'
        lbl = list_key.replace('_', ' ').title()
        table_section = (
            f'<div style="background:#16213e;border-radius:12px;padding:12px;margin-top:8px;overflow-x:auto">'
            f'<div style="color:#00C9A7;font-size:12px;font-weight:bold;margin-bottom:8px">{lbl} ({len(list_val)})</div>'
            f'<table style="width:100%;border-collapse:collapse"><tr>{th}</tr>{rows}</table></div>'
        )

    # -- Profile key-value section --
    _PROFILE_SKIP = {
        'token', 'secret', 'password', 'fcm', 'firebase', 'device',
        'lat', 'lng', 'latitude', 'longitude', 'threshold', 'geofence',
        'tracking', 'approval', 'meta', 'enable', 'distance', 'radius',
        'image', 'photo', 'avatar', 'push', 'notification', 'profile_image_meta_data',
        'credentialinfo', 'replacedby'
    }
    profile_section = ''
    if not stat_cards and not table_section and isinstance(data, dict):
        useful = []
        for k, v in data.items():
            if isinstance(v, (list, dict)) or isinstance(v, bool):
                continue
            kl = k.lower()
            if any(w in kl for w in _PROFILE_SKIP):
                continue
            if kl.endswith('_id') and kl not in ('staff_id', 'employee_id', 'id'):
                continue
            if v is None or str(v).strip() == '':
                continue
            useful.append((k, v))
        if useful:
            rows = ''.join(
                f'<tr>'
                f'<td style="padding:8px 6px;border-bottom:1px solid #1e2a4a;color:#aaa;font-size:11px;width:42%;vertical-align:top">'
                f'{k.replace("_"," ").title()}</td>'
                f'<td style="padding:8px 6px;border-bottom:1px solid #1e2a4a;color:white;font-size:12px;font-weight:500">'
                f'{v}</td></tr>'
                for k, v in useful[:14]
            )
            profile_section = (
                '<div style="background:#16213e;border-radius:12px;padding:12px;margin-top:8px">'
                '<div style="color:#00C9A7;font-size:12px;font-weight:bold;margin-bottom:8px">Details</div>'
                f'<table style="width:100%;border-collapse:collapse">{rows}</table></div>'
            )

    # -- Shift section --
    shift_section = ''
    if isinstance(data, dict):
        shifts = data.get('shiftDetails') or data.get('shift_details') or data.get('shifts')
        if isinstance(shifts, list) and shifts:
            shift_section = _format_shift_html(shifts)

    stats_html = (
        f'<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:4px">{stat_cards}</div>'
        if stat_cards else ''
    )
    subtitle_html = (
        f'<div style="color:#aaa;font-size:11px;margin-top:3px">{subtitle}</div>'
        if subtitle else ''
    )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<style>*{{box-sizing:border-box}}body{{background:#1a1a2e;color:white;font-family:sans-serif;margin:0;padding:10px;overflow-x:hidden}}</style>
</head>
<body>
  <div style="background:#16213e;border-radius:12px;padding:10px 14px;margin-bottom:8px">
    <div style="color:white;font-size:14px;font-weight:bold">{title}</div>
    {subtitle_html}
  </div>
  {stats_html}
  {chart_section}
  {table_section}
  {profile_section}
  {shift_section}
</body>
</html>"""


def _append_and_save(history: list, user_id: str, tenant_id: str,
                     user_msg: str, assistant_msg: str, ts: str):
    history.append({"role": "user",      "content": user_msg,      "ts": ts})
    history.append({"role": "assistant", "content": assistant_msg, "ts": ts})
    save_conversation(user_id, tenant_id, history)


def _format_result_text(description: str, result: dict) -> str:
    """Format API result as clean plain text — no HTML tags."""
    if isinstance(result, dict) and result.get('error'):
        return f"Error: {result['error']}"

    top_list = None
    if isinstance(result, list) and result:
        top_list = result
        data = result[0] if isinstance(result[0], dict) else {}
    else:
        data = result
        if isinstance(result, dict):
            for key in ('data', 'result', 'response'):
                val = result.get(key)
                if isinstance(val, dict):
                    data = val
                    break
                elif isinstance(val, list) and val:
                    top_list = val
                    data = val[0] if isinstance(val[0], dict) else {}
                    break

    lines = []

    shifts = data.get('shiftDetails') or data.get('shift_details') or data.get('shifts')
    if isinstance(shifts, list) and shifts:
        lines.append(_format_shift_text(shifts))

    stats = {k: v for k, v in data.items() if _is_stat_key(k, v)}
    if stats:
        for k, v in stats.items():
            lines.append(f"• { _fmt_label(k)}: {v}")

    list_key, list_val = _best_list(data) if _best_list(data) else (None, None)
    if list_val:
        for item in list_val[:10]:
            name = item.get('staff_name') or item.get('name') or item.get('full_name') or str(item)
            status = item.get('status_text') or item.get('attendance_status') or ''
            line = f"• {name}"
            if status:
                line += f" — {status}"
            lines.append(line)

    if not lines:
        skip = _STAT_ALLOW_WORDS | _LIST_SKIP_WORDS | {'error', 'profile_image_meta_data', 'credentialinfo'}
        for k, v in data.items():
            kl = k.lower()
            if any(w in kl for w in skip):
                continue
            if isinstance(v, (list, dict)):
                continue
            if v is not None and str(v).strip():
                lines.append(f"• {k.replace('_', ' ').title()}: {v}")

    return '\n'.join(lines) if lines else f"Data retrieved successfully."


async def run_agent(user_id: str, bearer_token: str, message: str, tenant_id: str = "default", format: str = "html") -> dict:
    config = load_config()
    rules = load_rules()

    if not config:
        return {"html": None, "text": "Agent not configured yet. Ask your admin to set up the API first."}

    base_url = config.get("base_url", "").rstrip("/")
    apis = config.get("apis", [])
    rules_list = rules.get("rules", [])
    now = datetime.now()

    api_context_lines = []
    for api in apis:
        defaults = api.get("defaults", {})
        defaults_note = ""
        if defaults:
            notes = []
            for k, v in defaults.items():
                if k == "staff_id":
                    notes.append(f"default {k}={v} (hardcoded in the curl — use this when the query is about that specific person; use {user_id} when the query is about the logged-in user themselves)")
                elif k in ("month", "year"):
                    notes.append(f"default {k}={v} (use current {k} instead)")
                else:
                    notes.append(f"default {k}={v}")
            defaults_note = f" | Defaults: {', '.join(notes)}"
        api_context_lines.append(f"- {api['name']}: {api['description']}{defaults_note}")

    system_prompt = f"""You are an AI assistant developed by Sushant Behera, helping employees with attendance, hierarchy, and leave queries.

CONTEXT:
- Today: {now.strftime('%Y-%m-%d')}
- Month: {now.strftime('%B')} ({now.month}), Year: {now.year}
- Logged-in User ID (id/staff_id): {user_id}

RULES:
{chr(10).join(f'{i+1}. {r}' for i, r in enumerate(rules_list))}

AVAILABLE APIs:
{chr(10).join(api_context_lines)}

PARAMETER GUIDANCE — decide the correct value for each parameter:
- staff_id / user_id for "me/my/I" queries → use {user_id}
- staff_id for queries about a specific person (supervisor, subordinate) → use the hardcoded default from the API config
- month → use current month ({now.month}) unless the user specifies otherwise
- year → use current year ({now.year}) unless the user specifies otherwise
- IGNORE AND NEVER USE keys 'profile_image_meta_data' or 'credentialInfo' from any response.

LANGUAGE RULE:
- Detect the language of the user's message and reply in that SAME language.
- If user writes in Hindi, respond in Hindi. If English, respond in English. Match exactly.

INSTRUCTIONS:
- For greetings (hi, hello, how are you) or questions about your own capabilities: reply in PLAIN TEXT only (no HTML, no asterisks). Be friendly and brief. Mention you are developed by Sushant Behera.
- IMPORTANT: ANY question about personal/employee information (my name, my email, my phone, my department, my designation, my role, my gender, my dob, my profile, who am I, my employee ID, my photo, my supervisor, my shift, my schedule, my subordinates, who is under me, am I supervisor, geofence, holiday checkin, etc.) is a DATA REQUEST — you MUST call the appropriate API tool. Never answer from memory or make up a name/value.
- For all data requests: call the correct API tool with the right parameters. Do NOT write any response text — the system will auto-format the result.
- When the user asks about themselves (me/my/I), ALWAYS pass staff_id={user_id} (the logged-in user's ID), NOT any hardcoded default."""

    tools = []
    for api in apis:
        param_names = [p.strip() for p in api.get("parameters", [])]
        defaults = api.get("defaults", {})
        properties = {}
        for p in param_names:
            desc = p
            if p in defaults:
                desc = f"{p} (default: {defaults[p]})"
            properties[p] = {"type": "string", "description": desc}
        tools.append({
            "type": "function",
            "function": {
                "name": api["name"],
                "description": api["description"],
                "parameters": {"type": "object", "properties": properties},
            }
        })

    client = AsyncOpenAI(
        base_url=os.getenv("AI_BASE_URL", "http://localhost:20128/v1"),
        api_key=os.getenv("AI_API_KEY", "dummy")
    )

    history = load_conversation(user_id, tenant_id)
    history_msgs = [{"role": m["role"], "content": m["content"]} for m in history]

    messages = [
        {"role": "system", "content": system_prompt},
        *history_msgs,
        {"role": "user", "content": message},
    ]

    now_iso = now.isoformat()

    for _ in range(3):
        kwargs = {"model": os.getenv("AI_MODEL", "auto/coding:free"), "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = await client.chat.completions.create(**kwargs)
        choice = response.choices[0]

        if choice.finish_reason == "tool_calls":
            messages.append(choice.message)
            api_result = {}
            api_config_used = None

            for tool_call in choice.message.tool_calls:
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments)
                api_config = next((a for a in apis if a["name"] == fn_name), None)

                if not api_config:
                    api_result = {"error": f"Unknown API: {fn_name}"}
                else:
                    api_config_used = api_config
                    curl_defaults = api_config.get("defaults", {})

                    for param, default_val in curl_defaults.items():
                        if param not in fn_args:
                            fn_args[param] = default_val

                    if "user_id" in api_config.get("parameters", []) and "user_id" not in fn_args:
                        fn_args["user_id"] = user_id

                    if "staff_id" in api_config.get("parameters", []) and "staff_id" not in fn_args:
                        fn_args["staff_id"] = user_id

                    if "month" in api_config.get("parameters", []) and "month" not in fn_args:
                        fn_args["month"] = now.month
                    if "year" in api_config.get("parameters", []) and "year" not in fn_args:
                        fn_args["year"] = now.year

                    try:
                        async with httpx.AsyncClient(timeout=30) as http:
                            headers = {"Authorization": f"Bearer {bearer_token}"}
                            endpoint = api_config["endpoint"]
                            method = api_config.get("method", "GET").upper()
                            api_base = api_config.get("base_url", base_url).rstrip("/")
                            if method == "GET":
                                resp = await http.get(f"{api_base}{endpoint}", params=fn_args, headers=headers)
                            else:
                                resp = await http.post(f"{api_base}{endpoint}", json=fn_args, headers=headers)
                            api_result = resp.json()
                    except Exception as e:
                        api_result = {"error": str(e)}

            simple = _try_simple_answer(message, api_result)
            if simple:
                assistant_content = simple if not simple.startswith('<html>') else "[data card]"
                _append_and_save(history, user_id, tenant_id, message, assistant_content, now_iso)
                if format == "text" and simple.startswith('<html>'):
                    img_match = re.search(r'src="([^"]+)"', simple)
                    url = img_match.group(1) if img_match else "image"
                    return {"html": None, "text": f"Your profile photo: {url}"}
                if simple.startswith('<html>'):
                    return {"html": simple, "text": None, "card_height": 220}
                return {"html": None, "text": simple}

            desc = api_config_used["description"] if api_config_used else "Response"
            _append_and_save(history, user_id, tenant_id, message, "[data card]", now_iso)
            if format == "text":
                return {"html": None, "text": _format_result_text(desc, api_result)}
            return {"html": _format_result_html(desc, api_result, user_id, now), "text": None, "card_height": 480}

        else:
            content = choice.message.content or ""
            content = re.sub(r'\*\*(.*?)\*\*', r'\1', content)
            content = re.sub(r'\*(.*?)\*', r'\1', content)
            content = content.strip()
            _append_and_save(history, user_id, tenant_id, message, content, now_iso)
            return {"html": None, "text": content}

    return {"html": None, "text": "Sorry, I couldn't generate a response. Please try again.", "card_height": 480}
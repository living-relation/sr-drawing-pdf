"""Command API for the sheet editor.

Every function takes a drawing dict (or None for a new drawing) and keyword
arguments, and returns {'document': <drawing dict>, 'result': <json>}.
The dict you pass is not changed. Keep the returned document and pass it
next time. That dict is ordinary JSON, so it survives a fresh import.

execute(document, command, args) is the same API with the command name in a
string, which is what an agent sends.

Inside Fusion, call SRDrawingPDF.editor_api() and use that module. Do not
put the add-in folder on sys.path yourself.
"""
import json

from .model import (
    BUILTIN_SIZES,
    TITLE_FIELDS,
    DrawingDocument,
    _observe,
    alloc_id,
    document_warnings,
    find_element,
    item_of,
    layout_bom as bom_layout,
    note_number,
    resolved_title,
    sheet_by_id,
    size_of,
)
from .revs import (
    drawn_by,
    format_rev,
    parse_rev,
    read_revlog,
    release_entries,
    table_rows,
    write_revlog,
)
from .settings import check_initials
from .render import export_pdf as write_document_pdf

API_ID = 'srDrawingPdfSheetApi'

COMMAND_DOCS = {
    'list_commands': 'Names and one-line summaries of every command.',
    'add_sheet': 'Add a sheet. Pass id to make a retry return the same sheet.',
    'remove_sheet': 'Remove a sheet and the items on it. Missing id is a no-op.',
    'reorder_sheets': 'Put the sheets in this order. The list must be every sheet id once.',
    'add_sheet_size': 'Register another sheet size on this drawing. Size B is built in.',
    'set_title': 'Set one linked title field. Every sheet reads it on the next export.',
    'title_block': 'The title-block values one sheet will draw, including sheet n of m.',
    'add_revision': 'Add or update a rev-log row. Clerical .01 revs are refused. Rev A sets DRAWN.',
    'revision_table': 'The rows the sheet-1 table will draw (newest window, no clerical revs).',
    'load_revlog': 'Replace the rev log with a REVLOG.md file.',
    'save_revlog': 'Write the rev log to a REVLOG.md file.',
    'set_draft': 'Set or clear the draft number. Does not change the rev letter or the log.',
    'add_bom_row': 'Add a BOM row, or update it when key already exists.',
    'edit_bom_row': 'Change fields on an existing BOM row.',
    'remove_bom_row': 'Remove a BOM row. Missing key is a no-op. Balloons keep the key.',
    'renumber_bom': 'Give the rows item numbers in list order. Balloons follow the keys.',
    'load_bom_csv': 'Load BOM rows from a CSV file or a CSV string.',
    'load_bom_components': 'Load BOM rows from plain component records (part number, description, material, qty).',
    'place_bom': 'Place or move a BOM region. Rows flow into regions and continue when one fills.',
    'move_bom': 'Move a BOM region. Same fields as place_bom; id is required.',
    'remove_bom': 'Remove a BOM region. Missing id is a no-op. Rows stay on the drawing.',
    'layout_bom': 'Which rows land in each region, and which do not fit.',
    'place_balloon': 'Place or move an item balloon. It stores a BOM key, not a frozen number.',
    'move_balloon': 'Move a balloon. id is required.',
    'delete_balloon': 'Delete a balloon. Missing id is a no-op.',
    'add_note': 'Add a note, or replace its text when key already exists.',
    'edit_note': 'Replace a note\'s text.',
    'delete_note': 'Delete a note. Missing key is a no-op. Later notes get new numbers.',
    'place_notes': 'Place or move the notes block on a sheet.',
    'move_notes': 'Move the notes block. id is required.',
    'delete_notes': 'Remove a notes block. Missing id is a no-op. The notes stay.',
    'place_note_flag': 'Place or move a note-flag balloon. It stores a note key.',
    'move_note_flag': 'Move a note flag. id is required.',
    'delete_note_flag': 'Delete a note flag. Missing id is a no-op.',
    'place_view': 'Place or move an empty view frame.',
    'move_view': 'Move or retitle a view frame. id is required.',
    'delete_view': 'Delete a view frame. Missing id is a no-op.',
    'sheet_marks': 'Balloons and note flags on one sheet, with the numbers they show now.',
    'check': 'Warnings: rev letter, initials, BOM overflow, dangling balloons. Export still works.',
    'export_pdf': 'Write the PDF. Returns the path, page count, and warnings.',
    'save': 'Save the drawing JSON.',
    'load': 'Replace this drawing with a JSON file.',
}


def execute(document, command, args=None):
    """Apply one command.

    document: a drawing dict from a previous result, or None to start a new one.
    command: a name from list_commands.
    args: a dict of arguments, or None.

    Returns {'document': <drawing dict>, 'result': <json value>}.
    """
    if not isinstance(command, str) or command not in COMMANDS:
        known = ', '.join(COMMANDS)
        raise ValueError('unknown command %r (known: %s)' % (command, known))
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise ValueError('args must be a dict')
    doc = DrawingDocument.from_dict(document)
    result = COMMANDS[command](doc, args)
    return {'document': doc.to_dict(), 'result': result}


def _sheet_info(doc, sheet, index):
    return {
        'id': sheet['id'],
        'name': sheet.get('name') or '',
        'size': sheet.get('size') or 'B',
        'scale': sheet.get('scale'),
        'index': index,
    }


def _cmd_list(doc, args):
    return {'commands': [{'name': name, 'summary': COMMAND_DOCS[name]} for name in COMMANDS]}


def _cmd_add_sheet(doc, args):
    sid = args.get('id')
    if sid:
        for i, sheet in enumerate(doc.sheets):
            if sheet.get('id') == sid:
                return _sheet_info(doc, sheet, i)
    size = args.get('size') or 'B'
    size_of(doc, size)
    if not sid:
        sid = alloc_id(doc, 'sheet')
    else:
        _observe(doc, sid)
    sheet = {
        'id': sid,
        'name': args.get('name') or ('Sheet %d' % (len(doc.sheets) + 1)),
        'size': size,
        'scale': args.get('scale'),
        'elements': [],
    }
    doc.sheets.append(sheet)
    return _sheet_info(doc, sheet, len(doc.sheets) - 1)


def _cmd_remove_sheet(doc, args):
    sid = args.get('id')
    for i, sheet in enumerate(doc.sheets):
        if sheet.get('id') == sid:
            del doc.sheets[i]
            return {'removed': True, 'id': sid}
    return {'removed': False, 'id': sid}


def _cmd_reorder(doc, args):
    order = list(args.get('order') or [])
    have = [s.get('id') for s in doc.sheets]
    if sorted(order) != sorted(have) or len(order) != len(have):
        raise ValueError('order must list each sheet id once')
    by_id = {s['id']: s for s in doc.sheets}
    doc.sheets = [by_id[i] for i in order]
    return {'order': [s['id'] for s in doc.sheets]}


def _cmd_add_size(doc, args):
    name = args.get('name')
    if not name or name == 'B':
        raise ValueError('choose a size name other than B')
    if name in BUILTIN_SIZES:
        raise ValueError('size %r is built in' % name)
    zones = args.get('zones') or [8, 4]
    doc.sizes[name] = {
        'width': float(args['width']),
        'height': float(args['height']),
        'label': args.get('label') or name,
        'zones': [int(zones[0]), int(zones[1])],
    }
    return {'name': name, 'size': doc.sizes[name]}


def _cmd_set_title(doc, args):
    field = args.get('field')
    if field not in TITLE_FIELDS:
        raise ValueError('unknown title field %r' % field)
    value = args.get('value')
    if field == 'rev' and value not in (None, ''):
        letter, clerical = parse_rev(value)
        value = format_rev(letter, clerical)
    if field == 'drawn' and value not in (None, ''):
        value = check_initials(value)
    if field == 'tol' and value == '':
        value = None
    doc.properties[field] = value
    return {'field': field, 'value': doc.properties[field]}


def _cmd_title_block(doc, args):
    index, sheet = sheet_by_id(doc, args.get('sheet'))
    info = resolved_title(doc, sheet, index + 1, len(doc.sheets))
    return {
        'project': info.get('project') or '',
        'title': info.get('title') or '',
        'pn': info.get('pn') or '',
        'rev': info.get('rev') or '',
        'material': info.get('material') or '',
        'scale': info.get('scale') or '',
        'units': info.get('units') or 'mm',
        'size': info.get('size_label') or '',
        'sheet': '%d OF %d' % (index + 1, len(doc.sheets)),
        'date': info.get('date') or '',
        'drawn': info.get('drawn') or '',
        'source': info.get('source') or '',
        'draft': doc.draft,
        'mark': ('DRAFT %d, NOT RELEASED' % doc.draft) if doc.draft else '',
    }


def _cmd_add_revision(doc, args):
    by = args.get('by')
    if not by:
        raise ValueError('by is required (initials of the person who asked for the change)')
    by = check_initials(by)
    letter, _clerical = parse_rev(args.get('rev'))
    doc.revlog = release_entries(doc.revlog, args.get('rev'), args.get('desc') or '', by, args.get('date'))
    current = doc.properties.get('rev') or ''
    try:
        current_letter = parse_rev(current)[0] if current else ''
    except ValueError:
        current_letter = ''
    if current_letter != letter:
        doc.properties['rev'] = letter
    if letter == 'A':
        doc.properties['drawn'] = by
    return {
        'rev': doc.properties.get('rev') or '',
        'drawn': doc.properties.get('drawn') or '',
        'rows': [{'rev': e.rev, 'desc': e.desc, 'by': e.by, 'date': e.date} for e in doc.revlog],
    }


def _cmd_revision_table(doc, args):
    rows = table_rows(doc.revlog)
    return {'rows': [{'rev': e.rev, 'desc': e.desc, 'by': e.by, 'date': e.date} for e in rows]}


def _cmd_load_revlog(doc, args):
    entries = read_revlog(args['path'])
    doc.revlog = entries
    rows = table_rows(entries)
    if rows and not doc.properties.get('rev'):
        doc.properties['rev'] = rows[-1].rev
    if not doc.properties.get('drawn'):
        who = drawn_by(entries)
        if who:
            doc.properties['drawn'] = who
    return {'rows': len(entries), 'rev': doc.properties.get('rev') or '', 'drawn': doc.properties.get('drawn') or ''}


def _cmd_save_revlog(doc, args):
    title = args.get('title') or doc.properties.get('pn') or ''
    write_revlog(args['path'], doc.revlog, title)
    return {'path': args['path'], 'rows': len(doc.revlog)}


def _cmd_set_draft(doc, args):
    n = args.get('n', None)
    if n in (None, ''):
        doc.draft = None
    else:
        n = int(n)
        if n < 1:
            raise ValueError('draft number must be 1 or more')
        doc.draft = n
    return {'draft': doc.draft}


def _row_from_args(args, key, item):
    shown = args.get('shown', True)
    return {
        'key': key,
        'item': item,
        'qty': _qty(args.get('qty', 1)),
        'pn': args.get('pn') or '',
        'desc': args.get('desc') or '',
        'mat': args.get('mat') or '',
        'shown': bool(shown) if shown is not None else True,
    }


def _qty(value):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value == int(value) else value
    text = str(value).strip()
    if text == '':
        return 1
    try:
        number = float(text)
    except ValueError:
        return text
    return int(number) if number == int(number) else number


def _cmd_add_bom_row(doc, args):
    key = args.get('key')
    if key:
        for row in doc.bom:
            if row.get('key') == key:
                for field in ('qty', 'pn', 'desc', 'mat', 'shown', 'item'):
                    if field in args:
                        row[field] = _qty(args[field]) if field == 'qty' else args[field]
                return {'key': key, 'item': row.get('item')}
    else:
        key = alloc_id(doc, 'bom')
    _observe(doc, key)
    if 'item' in args and args['item'] is not None:
        item = args['item']
    else:
        item = 1 + max([r.get('item') or 0 for r in doc.bom] or [0])
    doc.bom.append(_row_from_args(args, key, item))
    return {'key': key, 'item': item}


def _cmd_edit_bom_row(doc, args):
    key = args.get('key')
    for row in doc.bom:
        if row.get('key') == key:
            for field in ('qty', 'pn', 'desc', 'mat', 'shown', 'item'):
                if field in args:
                    row[field] = _qty(args[field]) if field == 'qty' else args[field]
            return {'key': key, 'item': row.get('item')}
    raise ValueError('no BOM row %r' % key)


def _cmd_remove_bom_row(doc, args):
    key = args.get('key')
    for i, row in enumerate(doc.bom):
        if row.get('key') == key:
            del doc.bom[i]
            return {'removed': True, 'key': key}
    return {'removed': False, 'key': key}


def _cmd_renumber(doc, args):
    n = int(args.get('start') or 1)
    items = []
    for row in doc.bom:
        row['item'] = n
        items.append({'key': row.get('key'), 'item': n})
        n += 1
    return {'items': items}


def _csv_rows(text):
    import csv
    import io
    found = []
    for rec in csv.DictReader(io.StringIO(text)):
        norm = {}
        for k, v in rec.items():
            norm[(k or '').strip().lower()] = (v or '').strip()

        def pick(*names):
            for name in names:
                if norm.get(name):
                    return norm[name]
            return ''

        shown = pick('shown')
        found.append({
            'item': pick('item'),
            'qty': pick('qty') or '1',
            'pn': pick('part number', 'part_number', 'pn'),
            'desc': pick('description', 'desc'),
            'mat': pick('material', 'material / spec', 'mat'),
            'shown': shown.lower() not in ('0', 'false', 'no', 'n') if shown else True,
            'key': pick('key'),
        })
    return found


def _take_rows(doc, rows, replace):
    if replace:
        doc.bom = []
    made = []
    for rec in rows:
        item = rec.get('item')
        if item in (None, ''):
            item = None
        else:
            item = _qty(item)
        key = rec.get('key') or None
        result = _cmd_add_bom_row(doc, {
            'key': key,
            'item': item,
            'qty': rec.get('qty', 1),
            'pn': rec.get('pn') or rec.get('part_number') or '',
            'desc': rec.get('desc') or rec.get('description') or '',
            'mat': rec.get('mat') or rec.get('material') or '',
            'shown': rec.get('shown', True),
        })
        made.append(result)
    return {'count': len(made), 'rows': made}


def _cmd_load_csv(doc, args):
    if args.get('text'):
        text = args['text']
    else:
        with open(args['path'], encoding='utf-8') as f:
            text = f.read()
    return _take_rows(doc, _csv_rows(text), bool(args.get('replace', True)))


def _cmd_load_components(doc, args):
    rows = []
    for rec in args.get('components') or []:
        rows.append({
            'key': rec.get('key'),
            'item': rec.get('item'),
            'qty': rec.get('qty', 1),
            'pn': rec.get('part_number', rec.get('pn', '')),
            'desc': rec.get('description', rec.get('desc', '')),
            'mat': rec.get('material', rec.get('mat', '')),
            'shown': rec.get('shown', True),
        })
    return _take_rows(doc, rows, bool(args.get('replace', True)))


def _upsert(doc, sheet_id, kind, id_, fields, required):
    sheet_index, sheet = sheet_by_id(doc, sheet_id)
    del sheet_index
    if id_:
        owner, el = find_element(doc, id_)
        if el is not None:
            if el.get('type') not in (None, kind):
                raise ValueError('id %r is a %s, not a %s' % (id_, el.get('type'), kind))
            if owner is not sheet:
                owner['elements'].remove(el)
                sheet['elements'].append(el)
            el['type'] = kind
            el.update(fields)
            return el
    else:
        id_ = alloc_id(doc, kind[:4] or 'el')
    missing = [name for name in required if name not in fields]
    if missing:
        raise ValueError('%s is required' % missing[0])
    _observe(doc, id_)
    el = {'id': id_, 'type': kind}
    el.update(fields)
    sheet['elements'].append(el)
    return el


def _bom_fields(args, existing):
    fields = {}
    for key in ('x1', 'ytop', 'max_height', 'text_h'):
        if key in args and args[key] is not None:
            fields[key] = float(args[key])
    if 'colw' in args and args['colw'] is not None:
        fields['colw'] = [float(c) for c in args['colw']]
    if 'max_height' in fields and fields['max_height'] <= 0:
        raise ValueError('max_height must be greater than 0')
    if existing is None:
        for key in ('x1', 'ytop', 'max_height'):
            if key not in fields:
                raise ValueError('%s is required' % key)
    return fields


def _cmd_place_bom(doc, args):
    existing_sheet, existing = find_element(doc, args.get('id')) if args.get('id') else (None, None)
    sheet_id = args.get('sheet') or (existing_sheet.get('id') if existing_sheet else None)
    if not sheet_id:
        raise ValueError('sheet is required')
    el = _upsert(doc, sheet_id, 'bom', args.get('id'), _bom_fields(args, existing), ('x1', 'ytop', 'max_height'))
    layout = bom_layout(doc)
    segment = next(seg for seg in layout['segments'] if seg['id'] == el['id'])
    return {'id': el['id'], 'segment': segment, 'overflow': layout['overflow']}


def _cmd_move_bom(doc, args):
    if not args.get('id'):
        raise ValueError('id is required')
    return _cmd_place_bom(doc, args)


def _delete_element(doc, element_id, kind):
    for sheet in doc.sheets:
        elements = sheet.get('elements') or []
        for i, el in enumerate(elements):
            if el.get('id') == element_id and el.get('type') == kind:
                del elements[i]
                return {'removed': True, 'id': element_id}
    return {'removed': False, 'id': element_id}


def _cmd_remove_bom(doc, args):
    return _delete_element(doc, args.get('id'), 'bom')


def _cmd_layout(doc, args):
    return bom_layout(doc)


def _num_fields(args, names):
    out = {}
    for name in names:
        if name in args and args[name] is not None:
            out[name] = float(args[name])
    return out


def _cmd_place_balloon(doc, args):
    existing_sheet, existing = find_element(doc, args.get('id')) if args.get('id') else (None, None)
    sheet_id = args.get('sheet') or (existing_sheet.get('id') if existing_sheet else None)
    if not sheet_id:
        raise ValueError('sheet is required')
    fields = _num_fields(args, ('x', 'y', 'ax', 'ay'))
    if 'bom_key' in args and args['bom_key'] is not None:
        fields['bom_key'] = args['bom_key']
    if existing is None and 'bom_key' not in fields:
        raise ValueError('bom_key is required')
    el = _upsert(doc, sheet_id, 'balloon', args.get('id'), fields, ('x', 'y', 'ax', 'ay', 'bom_key'))
    return {'id': el['id'], 'bom_key': el.get('bom_key'), 'item': item_of(doc, el.get('bom_key'))}


def _cmd_move_balloon(doc, args):
    if not args.get('id'):
        raise ValueError('id is required')
    return _cmd_place_balloon(doc, args)


def _cmd_delete_balloon(doc, args):
    return _delete_element(doc, args.get('id'), 'balloon')


def _cmd_add_note(doc, args):
    key = args.get('key')
    text = args.get('text') or ''
    if key:
        for i, note in enumerate(doc.notes, 1):
            if note.get('key') == key:
                note['text'] = text
                return {'key': key, 'number': i}
    else:
        key = alloc_id(doc, 'note')
    _observe(doc, key)
    doc.notes.append({'key': key, 'text': text})
    return {'key': key, 'number': len(doc.notes)}


def _cmd_edit_note(doc, args):
    key = args.get('key')
    for i, note in enumerate(doc.notes, 1):
        if note.get('key') == key:
            note['text'] = args.get('text') or ''
            return {'key': key, 'number': i}
    raise ValueError('no note %r' % key)


def _cmd_delete_note(doc, args):
    key = args.get('key')
    for i, note in enumerate(doc.notes):
        if note.get('key') == key:
            del doc.notes[i]
            return {'removed': True, 'key': key}
    return {'removed': False, 'key': key}


def _cmd_place_notes(doc, args):
    existing_sheet, existing = find_element(doc, args.get('id')) if args.get('id') else (None, None)
    sheet_id = args.get('sheet') or (existing_sheet.get('id') if existing_sheet else None)
    if not sheet_id:
        raise ValueError('sheet is required')
    fields = _num_fields(args, ('x', 'y', 'width', 'text_h'))
    el = _upsert(doc, sheet_id, 'notes', args.get('id'), fields, ('x', 'y'))
    return {'id': el['id']}


def _cmd_move_notes(doc, args):
    if not args.get('id'):
        raise ValueError('id is required')
    return _cmd_place_notes(doc, args)


def _cmd_delete_notes(doc, args):
    return _delete_element(doc, args.get('id'), 'notes')


def _cmd_place_flag(doc, args):
    existing_sheet, existing = find_element(doc, args.get('id')) if args.get('id') else (None, None)
    sheet_id = args.get('sheet') or (existing_sheet.get('id') if existing_sheet else None)
    if not sheet_id:
        raise ValueError('sheet is required')
    fields = _num_fields(args, ('x', 'y', 'ax', 'ay'))
    if 'note_key' in args and args['note_key'] is not None:
        fields['note_key'] = args['note_key']
    if existing is None and 'note_key' not in fields:
        raise ValueError('note_key is required')
    el = _upsert(doc, sheet_id, 'note_flag', args.get('id'), fields, ('x', 'y', 'ax', 'ay', 'note_key'))
    return {'id': el['id'], 'note_key': el.get('note_key'), 'number': note_number(doc, el.get('note_key'))}


def _cmd_move_flag(doc, args):
    if not args.get('id'):
        raise ValueError('id is required')
    return _cmd_place_flag(doc, args)


def _cmd_delete_flag(doc, args):
    return _delete_element(doc, args.get('id'), 'note_flag')


def _cmd_place_view(doc, args):
    existing_sheet, existing = find_element(doc, args.get('id')) if args.get('id') else (None, None)
    sheet_id = args.get('sheet') or (existing_sheet.get('id') if existing_sheet else None)
    if not sheet_id:
        raise ValueError('sheet is required')
    fields = _num_fields(args, ('x', 'y', 'w', 'h'))
    if 'label' in args and args['label'] is not None:
        fields['label'] = args['label']
    if 'scale' in args:
        fields['scale'] = args['scale']
    el = _upsert(doc, sheet_id, 'view', args.get('id'), fields, ('x', 'y', 'w', 'h'))
    return {'id': el['id'], 'label': el.get('label') or ''}


def _cmd_move_view(doc, args):
    if not args.get('id'):
        raise ValueError('id is required')
    return _cmd_place_view(doc, args)


def _cmd_delete_view(doc, args):
    return _delete_element(doc, args.get('id'), 'view')


def _cmd_marks(doc, args):
    _index, sheet = sheet_by_id(doc, args.get('sheet'))
    balloons = []
    flags = []
    for el in sheet.get('elements') or []:
        if el.get('type') == 'balloon':
            balloons.append({
                'id': el.get('id'),
                'bom_key': el.get('bom_key'),
                'item': item_of(doc, el.get('bom_key')),
                'x': el.get('x'),
                'y': el.get('y'),
                'ax': el.get('ax'),
                'ay': el.get('ay'),
            })
        elif el.get('type') == 'note_flag':
            flags.append({
                'id': el.get('id'),
                'note_key': el.get('note_key'),
                'number': note_number(doc, el.get('note_key')),
                'x': el.get('x'),
                'y': el.get('y'),
                'ax': el.get('ax'),
                'ay': el.get('ay'),
            })
    return {'balloons': balloons, 'note_flags': flags}


def _cmd_check(doc, args):
    return {'warnings': document_warnings(doc)}


def _cmd_export(doc, args):
    path = args['path']
    pages, missing = write_document_pdf(doc, path)
    warnings = document_warnings(doc)
    if missing:
        warnings.append('font has no glyph for: %s' % ''.join(missing))
    return {'path': path, 'pages': pages, 'warnings': warnings}


def _cmd_save(doc, args):
    path = args['path']
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(doc.to_dict(), f, indent=1)
        f.write('\n')
    return {'path': path}


def _cmd_load(doc, args):
    with open(args['path'], encoding='utf-8') as f:
        loaded = DrawingDocument.from_dict(json.load(f))
    doc.__dict__.clear()
    doc.__dict__.update(loaded.__dict__)
    return {'path': args['path'], 'sheets': len(doc.sheets)}


COMMANDS = {
    'list_commands': _cmd_list,
    'add_sheet': _cmd_add_sheet,
    'remove_sheet': _cmd_remove_sheet,
    'reorder_sheets': _cmd_reorder,
    'add_sheet_size': _cmd_add_size,
    'set_title': _cmd_set_title,
    'title_block': _cmd_title_block,
    'add_revision': _cmd_add_revision,
    'revision_table': _cmd_revision_table,
    'load_revlog': _cmd_load_revlog,
    'save_revlog': _cmd_save_revlog,
    'set_draft': _cmd_set_draft,
    'add_bom_row': _cmd_add_bom_row,
    'edit_bom_row': _cmd_edit_bom_row,
    'remove_bom_row': _cmd_remove_bom_row,
    'renumber_bom': _cmd_renumber,
    'load_bom_csv': _cmd_load_csv,
    'load_bom_components': _cmd_load_components,
    'place_bom': _cmd_place_bom,
    'move_bom': _cmd_move_bom,
    'remove_bom': _cmd_remove_bom,
    'layout_bom': _cmd_layout,
    'place_balloon': _cmd_place_balloon,
    'move_balloon': _cmd_move_balloon,
    'delete_balloon': _cmd_delete_balloon,
    'add_note': _cmd_add_note,
    'edit_note': _cmd_edit_note,
    'delete_note': _cmd_delete_note,
    'place_notes': _cmd_place_notes,
    'move_notes': _cmd_move_notes,
    'delete_notes': _cmd_delete_notes,
    'place_note_flag': _cmd_place_flag,
    'move_note_flag': _cmd_move_flag,
    'delete_note_flag': _cmd_delete_flag,
    'place_view': _cmd_place_view,
    'move_view': _cmd_move_view,
    'delete_view': _cmd_delete_view,
    'sheet_marks': _cmd_marks,
    'check': _cmd_check,
    'export_pdf': _cmd_export,
    'save': _cmd_save,
    'load': _cmd_load,
}


def _bind(name):
    def fn(document, **kwargs):
        return execute(document, name, kwargs)
    fn.__name__ = name
    fn.__doc__ = COMMAND_DOCS[name]
    return fn


list_commands = _bind('list_commands')
add_sheet = _bind('add_sheet')
remove_sheet = _bind('remove_sheet')
reorder_sheets = _bind('reorder_sheets')
add_sheet_size = _bind('add_sheet_size')
set_title = _bind('set_title')
title_block = _bind('title_block')
add_revision = _bind('add_revision')
revision_table = _bind('revision_table')
load_revlog = _bind('load_revlog')
save_revlog = _bind('save_revlog')
set_draft = _bind('set_draft')
add_bom_row = _bind('add_bom_row')
edit_bom_row = _bind('edit_bom_row')
remove_bom_row = _bind('remove_bom_row')
renumber_bom = _bind('renumber_bom')
load_bom_csv = _bind('load_bom_csv')
load_bom_components = _bind('load_bom_components')
place_bom = _bind('place_bom')
move_bom = _bind('move_bom')
remove_bom = _bind('remove_bom')
layout_bom = _bind('layout_bom')
place_balloon = _bind('place_balloon')
move_balloon = _bind('move_balloon')
delete_balloon = _bind('delete_balloon')
add_note = _bind('add_note')
edit_note = _bind('edit_note')
delete_note = _bind('delete_note')
place_notes = _bind('place_notes')
move_notes = _bind('move_notes')
delete_notes = _bind('delete_notes')
place_note_flag = _bind('place_note_flag')
move_note_flag = _bind('move_note_flag')
delete_note_flag = _bind('delete_note_flag')
place_view = _bind('place_view')
move_view = _bind('move_view')
delete_view = _bind('delete_view')
sheet_marks = _bind('sheet_marks')
check = _bind('check')
export_pdf = _bind('export_pdf')
save = _bind('save')
load = _bind('load')

#!/usr/bin/env python


def fixture_to_tables(fixture):
    ''' convert fixture into *behave* examples
    :param fixture: a dictionary in the following form::

        {
            "test1name":
            {
                "test1property1": ...,
                "test1property2": ...,
                ...
            },
            "test2name":
            {
                "test2property1": ...,
                "test2property2": ...,
                ...
            }
        }

    :return: a list, with each item represent a table: `(caption, rows)`,
    each item in `rows` is `(col1, col2,...)`
    '''

    tables = []
    for (title, content) in fixture.iteritems():
        rows = []

        # header(keyword) row
        keys = content.keys()
        keys.sort()
        rows.append(tuple(keys))

        # item(value) row
        row1 = []
        for col in rows[0]:
            row1.append(content[col])
        rows.append(tuple(row1))

        tables.append((title, tuple(rows)))
    return tables


def format_item(item, py=True):
    '''
    :param py: python format or not
    '''
    # for non python format, just output itself.
    # so the result is `something` instead of `"something"`
    if not py:
        return unicode(item)

    if isinstance(item, (str, unicode)):
        # long int is prefixed by a #
        if item.startswith('#'):
            return unicode(long(item[1:]))
        return u'"{0}"'.format(item)

    return unicode(item)


def format_to_example(table, tabspace=2, indent=2):
    ''' format table to *behave* example
    :param table: `(caption, rows)`, each item in `rows` is `(col1, col2,...)`
    :return
    '''
    from io import StringIO
    output = StringIO()

    caption, rows = table

    # output caption line
    output.write(u'{0}Examples: {1}\n'.format(' ' * indent * tabspace,
                                              caption))

    # calculate max length for each column, for aligning
    cols = zip(*rows)
    col_lengths = []
    for col in cols:
        max_length = max([len(format_item(row)) for row in col])
        col_lengths.append(max_length)

    # output each row
    for r, row in enumerate(rows):
        output.write(u' ' * (indent + 1) * tabspace)
        output.write(u'|')
        for c in range(len(col_lengths)):
            output.write(u' ')
            output.write(format_item(row[c], r))
            output.write(u' ' * (col_lengths[c] - len(format_item(row[c], r))))
            output.write(u' |')
        output.write(u'\n')

    example = output.getvalue()
    output.close()
    return example


if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print('Please give the json fixture file path')

    f = sys.argv[1]
    fixture = json.load(file(f))
    tables = fixture_to_tables(fixture)
    for table in tables:
        print(format_to_example(table))

@given(u'an Even length hex string')
def step_impl(context):
    assert False

@when(u'compactly encoded')
def step_impl(context):
    assert False

@then(u'the first byte should be 0x00')
def step_impl(context):
    assert False

@then(u'the remain bits with be same of the original hex string')
def step_impl(context):
    assert False

@then(u'decode the compactly encoded hex string will get the original hex string')
def step_impl(context):
    assert False

@given(u'an odd length hex string')
def step_impl(context):
    assert False

@then(u'the first byte should start with 0x1')
def step_impl(context):
    assert False

@when(u'append a terminator')
def step_impl(context):
    assert False

@then(u'the first byte should start with 0x2')
def step_impl(context):
    assert False

@then(u'the first byte should start with 0x3')
def step_impl(context):
    assert False

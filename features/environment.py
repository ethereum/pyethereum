from trie_hook import trie_feature_hooker

def before_feature(context, feature):
    if feature.name == 'trie tree manipulate':
        trie_feature_hooker.before(context, feature)

def after_feature(context, feature):
    if feature.name == 'trie tree manipulate':
        trie_feature_hooker.after(context, feature)

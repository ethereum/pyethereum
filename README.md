# [Ethereum](http://ethereum.org/)
A next-generation smart contract and decentralized application platform.

## Features
- [Novel "memory-hard" hashing algorithm specification](http://wiki.ethereum.org/index.php/Dagger)
- [Use of GHOST blocktrees instead of a traditional blockchain for PoW data propagation](https://eprint.iacr.org/2013/881.pdf)
- Use of [Patricia trees](http://wiki.ethereum.org/index.php/Patricia_Tree) in block data structures
- Transactions which contain loop-enabled programmable instructions for the creation of novel derivatives and functions within the blocktree; these are deemed "contracts"
- New fees algorithm which adjusts based on several different parameters
- New difficulty adjustment algorithm
- Data in objects is encoded in recursive length prefix (RLP) notation
- Crowdfunding model

## Resources

- [Whitepaper](http://ethereum.org/ethereum.html)
- [Source Code](https://github.com/ethereum)

## Summary
In the last few months, there has been a great amount of interest into the area of using Bitcoin-like blockchains, the mechanism that allows for the entire world to agree on the state of a public ownership database, for more than just money. Commonly cited applications include using on-blockchain digital assets to represent custom currencies and financial instruments ("colored coins"), "smart property" devices such as cars which track a colored coin on a blockchain to determine their present legitimate owner, as well as more advanced applications such as decentralized exchange, financial derivatives, peer-to-peer gambling and on-blockchain identity and reputation systems. Perhaps the most ambitious of all is the concept of autonomous agents or [decentralized autonomous corporations](http://bitcoinmagazine.com/7050/bootstrapping-a-decentralized-autonomous-corporation-part-i/) - autonomous entities that operate on the blockchain without any central control whatsoever, eschewing all dependence on legal contracts and organizational bylaws in favor of having resources and funds autonomously managed by a self-enforcing smart contract on a cryptographic blockchain.

However, most of these applications are difficult to implement today, simply because the scripting systems of Bitcoin, and even next-generation cryptocurrency protocols such as the Bitcoin-based colored coins protocol and so-called "metacoins", are far too limited to allow the kind of arbitrarily complex computation that DACs require. What this project intends to do is take the innovations that such protocols bring, and generalize them - create a fully-fledged, Turing-complete (but heavily fee-regulated) cryptographic ledger that allows participants to encode arbitrarily complex contracts, autonomous agents and relationships that will be mediated entirely by the blockchain. Rather than being limited to a specific set of transaction types, users will be able to use Ethereum as a sort of "Lego of crypto-finance" - that is to say, one will be able to implement any feature that one desires simply by coding it in the protocol's internal scripting language. Custom currencies, financial derivatives, identity systems and decentralized organizations will all be easy to do, and it will also be possible to construct transaction types that even the Ethereum developers did not imagine. Altogether, we believe that this design is a solid step toward the realization of "cryptocurrency 2.0"; we hope that Ethereum will be as significant an addition to the cryptocurrency ecosystem as Web 2.0 was to the World Wide Web circa 1995.

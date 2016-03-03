INCENTIVIZATION_EMA_COEFF = 300
VALIDATOR_ROUNDS = 6
BLKTIME = 7.5
LOWCAP, HIGHCAP = 0, 255
DESIRED_ANNUAL_MAXRETURN = 0.1

def logoddsToOdds(logodds):
    return 2**(logodds // 4) * (4 + (logodds) % 4) * 99 / 1700

MAXODDS = logoddsToOdds(HIGHCAP) / 10**9

def scoreCorrect(logodds, odds):
    return (max(logodds - 128, 0) * MAXODDS / 128 * 10**9 + odds) / 10000

def scoreIncorrect(odds):
    return (0 - max(odds - 10**9, 0) * MAXODDS / 128 * 10 / 7 * 4 - odds * odds / 2 / 10**9) / 10000

s = [0] * 256
f = [0] * 256
for i in range(LOWCAP, HIGHCAP + 1):
    s[i] = scoreCorrect(i, logoddsToOdds(i))
    f[i] = scoreIncorrect(logoddsToOdds(i))
    if i > 12:
        rat = (f[i] - f[i-1]) * 1.0 / (s[i] - s[i-1] + 0.0000000001)
        print 'Logodds', i, 'sdiff', s[i], 'fdiff', f[i], 'odds', logoddsToOdds(i) * 10**-9, 'ratio', rat


def annualPercent(i):
    return (1 + i)**(31556926./BLKTIME)*100-100

print 'maxodds', MAXODDS
maxdivisor = -scoreIncorrect(logoddsToOdds(HIGHCAP)) * VALIDATOR_ROUNDS / INCENTIVIZATION_EMA_COEFF
print 'maxdivisor', maxdivisor
interest_per_block = (scoreCorrect(HIGHCAP, logoddsToOdds(HIGHCAP)) * 1.0 / maxdivisor)
print 'earnings per block: %.2f ppb, %.2f%% annualized, for 1500 eth: %d' % (interest_per_block*10**9, annualPercent(interest_per_block), interest_per_block*1500*10**18)
interest_per_block_cum = interest_per_block * 2
print 'earnings per block incl stateroots: %.2f ppb, %.2f%% annualized, for 1500 eth: %d' % (interest_per_block_cum*10**9, annualPercent(interest_per_block_cum), interest_per_block_cum*1500*10**18)
demurrage = interest_per_block_cum - (1.1**(BLKTIME/31556926.) - 1)
print 'recommended demurrage ppb: %.2f, %.2f%% annualized' % (demurrage * 10**9, annualPercent(demurrage))

// Narration for the OrbitGuard demo video, split into lines so on-screen actions can be
// cued to the moment each line starts. Every number here must match docs/RESULTS.md.
export const VOICE = 'Samantha';
export const RATE = 182; // words per minute for `say`

export const SCENES = [
  {id: 'title', lead: 2.2, tail: 1.4, lines: [
    'OrbitGuard.',
    'Avoid one collision, without causing another.',
  ]},
  {id: 'problem', lead: 0.3, tail: 0.7, lines: [
    'Low Earth orbit is getting crowded.',
    'Tens of thousands of objects are tracked, and satellite operators receive a constant stream of close-approach alerts.',
    'In 2009, Iridium 33 and Cosmos 2251 collided, creating more than two thousand pieces of trackable debris.',
    'So satellites dodge.',
    'But a dodge changes the orbit, and the new orbit can lead straight into something else.',
  ]},
  {id: 'solution', lead: 0.3, tail: 0.6, lines: [
    'OrbitGuard is a decision-support console for satellite operators, and it does three things.',
    'It forecasts how risky each encounter will become, using real alert data from the European Space Agency.',
    'It screens thirty-seven candidate burns against every nearby object, not just the one that raised the alert.',
    'And it recommends the smallest burn that keeps every encounter safe, or says clearly when none exists.',
  ]},
  {id: 'linuxone', lead: 0.5, tail: 1.6, lines: [
    'All of it runs on IBM LinuxONE.',
    'Training, evaluation, the orbital physics, and the web service you are about to see, on an s390x virtual machine.',
  ]},
  {id: 'encounters', lead: 0.4, tail: 1.4, lines: [
    'This is the encounter monitor, with real conjunction alerts from ESA\'s Collision Avoidance Challenge.',
    'Each encounter is a series of messages issued in the days before closest approach. We replay them, and forecast the final risk using only what was known forty-eight hours ahead.',
    'Every technical term explains itself when you hover over it.',
    'Below are the two orbits involved,',
    'and all two thousand one hundred and sixty-seven test encounters, plotted by orbit. The dense bands are orbits crowded with debris.',
  ]},
  {id: 'planning', lead: 0.4, tail: 2.2, lines: [
    'Now the core problem, in a simulated neighbourhood of eight objects. Satellite A is heading for object B.',
    'We press screen, and LinuxONE evaluates every candidate burn against every object, at three levels of position uncertainty, in under two seconds.',
    'The cheapest burn that avoids B slows the satellite by five centimetres per second.',
    'But watch the distance to object C.',
    'At minute one hundred, A passes within fifteen metres of C. A two percent chance of collision, far above the limit.',
    'OrbitGuard rejects that burn, and speeds the satellite up by the same five centimetres per second instead.',
    'Same fuel, and every encounter stays below one in ten thousand.',
  ]},
  {id: 'validation', lead: 0.4, tail: 0.8, lines: [
    'Is it right? We checked three ways.',
    'On ESA\'s held-out test set, our scoring reproduces ESA\'s published baseline exactly. Our learned model ranks dangerous encounters better, with a confidence interval that excludes zero. Where it was not better, we say so, and keep the baseline.',
    'Our collision probability code matches NASA\'s reference cases to within three parts per million.',
    'And across fifty stress-test scenarios, avoiding only the original threat created twenty new hazards. OrbitGuard created none, for the same average fuel.',
  ]},
  {id: 'outro', lead: 0.3, tail: 1.6, lines: [
    'OrbitGuard. Real data, independent checks, running on IBM LinuxONE.',
    'One decision that protects every nearby orbit.',
  ]},
];

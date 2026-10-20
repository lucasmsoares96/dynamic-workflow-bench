export const meta = {
  name: 'bench-t1',
  description: 'Chama o subagente bench-researcher uma unica vez',
  phases: [{ title: 'Execution' }]
}

const taskPrompt = typeof args === 'string' ? args : (args && args.task ? args.task : String(args))
const result = await agent(taskPrompt, {
  label: 'exec',
  phase: 'Execution',
  agentType: 'bench-researcher'
})
return { result }

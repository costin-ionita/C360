import SectionCard from './SectionCard'

export default function ReportView({ sections }) {
  const header = sections.find((s) => s.type === 'header')
  const body = sections.filter((s) => s.type !== 'header')

  return (
    <div className="space-y-8">
      {header && <header dangerouslySetInnerHTML={{ __html: header.html }} />}
      {body.map((section) => (
        <SectionCard key={section.id} section={section} />
      ))}
    </div>
  )
}

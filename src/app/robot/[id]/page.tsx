import ClientPage from '@/app/client-page';

{/* Note, since my colleagues are still working on getting this running with multiple robots, this is just a temporary solution, but this will eventually show the dashboard for each individual robot */}
export function generateStaticParams() {
  return [
    { id: 'tb3_0' },
    { id: 'tb3_1' },
    { id: 'tb3_2' },
  ];
}

export default function RobotPage() {
  return <ClientPage />;
}